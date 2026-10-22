#!/usr/bin/env python3
"""Inventory packaged Python distributions and native objects without executing them."""
import argparse
import email
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import zipfile


def inventory(path):
    packages, native = [], []

    def visit(name, data, depth=0):
        if depth > 4:
            raise ValueError('Archive nesting limit')
        if name.endswith(('/METADATA', '/PKG-INFO')):
            metadata = email.message_from_bytes(data)
            if metadata.get('Name'):
                packages.append({'path': name, 'name': metadata['Name'], 'version': metadata.get('Version'),
                                 'license': metadata.get('License-Expression') or metadata.get('License')})
        elif name.endswith('.so'):
            native.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest(),
                           'version_strings': sorted(set(m.decode() for m in re.findall(rb'(?:OpenSSL [0-9][0-9a-zA-Z. +_-]{0,35}|go1\.[0-9]+\.[0-9]+)', data)))})
        elif data.startswith(b'PK\x03\x04'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for entry in archive.infolist():
                    if not entry.is_dir():
                        visit(name + ':' + entry.filename, archive.read(entry), depth + 1)
        elif name.endswith(('.tgz', '.tar.gz')):
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                for entry in archive.getmembers():
                    if entry.isfile():
                        visit(name + ':' + entry.name, archive.extractfile(entry).read(), depth + 1)

    visit(path.name, path.read_bytes())
    return {'apk': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'python_distributions': packages, 'native_libraries': native,
            'scope': 'Package metadata and embedded version strings, not a vulnerability-free attestation.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('apk', type=Path)
    print(json.dumps(inventory(parser.parse_args().apk), indent=2))
