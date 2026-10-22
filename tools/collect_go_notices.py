#!/usr/bin/env python3
"""Collect license texts from the resolved mesh module sources for distribution."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    raw = subprocess.check_output(['go', 'list', '-deps', '-json', '.'], cwd=ROOT / 'tsbridge', text=True)
    modules, decoder = {}, json.JSONDecoder()
    while raw.strip():
        package, size = decoder.raw_decode(raw.lstrip())
        raw = raw.lstrip()[size:]
        module = package.get('Module')
        if module and not module.get('Main'):
            module = module.get('Replace', module)
            modules[module['Path']] = module
    output = ROOT / 'build/go-notices'
    output.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, module in sorted(modules.items()):
        files = [p for p in Path(module['Dir']).iterdir()
                 if p.is_file() and re.match(r'^(licen[cs]e|copying|notice)', p.name, re.I)]
        if not files:
            raise ValueError('No license found for ' + name)
        for file in files:
            (output / (name.replace('/', '__') + '--' + file.name)).write_bytes(file.read_bytes())
        manifest.append({'module': name, 'version': module.get('Version'), 'licenses': [p.name for p in files]})
    goroot = Path(subprocess.check_output(['go', 'env', 'GOROOT'], text=True).strip())
    license_path = next(p for p in (goroot / 'LICENSE', goroot.parent / 'LICENSE') if p.is_file())
    (output / 'Go-LICENSE').write_bytes(license_path.read_bytes())
    (output / 'modules.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Go license modules:', len(manifest))


if __name__ == '__main__':
    main()
