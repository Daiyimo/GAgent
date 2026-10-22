import importlib.util
import marshal
from pathlib import Path
import zipfile


spec = importlib.util.spec_from_file_location('prepare_python_assets', Path(__file__).parents[1] / 'tools/prepare_python_assets.py')
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


def test_path_cleanup_preserves_serialized_code_and_archive(tmp_path):
    filename = '/Users/' + 'upstream-builder/package/module.py'
    code = compile('result = 6 * 7', filename, 'exec')
    payload = marshal.dumps(code)
    with zipfile.ZipFile(tmp_path / 'stdlib-common.imy', 'w') as archive:
        archive.writestr('module.pyc', payload)
    assets.prepare(tmp_path)
    with zipfile.ZipFile(tmp_path / 'stdlib-common.imy') as archive:
        cleaned = archive.read('module.pyc')
    assert len(cleaned) == len(payload)
    assert not assets.BUILD_USER.search(cleaned)
    environment = {}
    exec(marshal.loads(cleaned), environment)
    assert environment['result'] == 42


def test_ca_replacement_uses_pinned_public_bundle(tmp_path):
    ca = tmp_path / 'cacert.pem'
    ca.write_bytes(b'old certificate bundle')
    assets.prepare(tmp_path)
    assert ca.read_bytes().count(b'BEGIN CERTIFICATE') > 50
