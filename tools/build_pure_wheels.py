#!/usr/bin/env python3
"""Build portable, patched HTTP dependencies without Android C extensions."""
import os
from pathlib import Path
import subprocess
import sys

PACKAGES = ('aiohttp==3.14.5', 'multidict==7.1.0', 'yarl==1.25.1',
            'frozenlist==1.8.0', 'propcache==0.5.4')


def main():
    output = Path(__file__).resolve().parents[1] / 'build/python-wheels'
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    for name in ('AIOHTTP', 'MULTIDICT', 'YARL', 'FROZENLIST', 'PROPCACHE'):
        environment[name + '_NO_EXTENSIONS'] = '1'
    subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps',
                    '--no-binary=' + ','.join(p.split('==')[0] for p in PACKAGES),
                    '--wheel-dir', str(output), *PACKAGES],
                   env=environment, check=True, timeout=600)
    for package in PACKAGES:
        name, version = package.split('==')
        if not list(output.glob(name + '-' + version + '-py3-none-any.whl')):
            raise RuntimeError('A portable wheel was not produced for ' + package)


if __name__ == '__main__':
    main()
