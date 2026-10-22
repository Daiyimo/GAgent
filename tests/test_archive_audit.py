import importlib.util
import io
from pathlib import Path
import zipfile


spec = importlib.util.spec_from_file_location('audit_source', Path(__file__).parents[1] / 'tools/audit_source.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def packed(name, payload):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, payload)
    return output.getvalue()


def test_nested_chaquopy_payload_is_checked_without_disclosing_value():
    value = b'sk-' + b'x' * 24
    nested = packed('assets/app.imy', packed('module.pyc', value))
    findings = audit.audit_archive('candidate.apk', nested)
    assert any(f['rule'] == 'provider-token' and 'module.pyc' in f['path'] for f in findings)
    assert value.decode() not in str(findings)


def test_nested_runtime_credentials_and_traversal_are_rejected():
    assert audit.audit_archive('app.imy', packed('kv/.bus_token', b'example'))[0]['rule'] == 'credential-or-runtime-file'
    assert audit.audit_archive('app.imy', packed('../outside', b'example'))[0]['rule'] == 'unsafe-archive-member'


def test_key_format_marker_is_not_a_key_but_payload_is_rejected():
    marker = b'-----BEGIN ' + b'PRIVATE KEY-----'
    assert not audit.audit_blob('ssh.pyc', marker)
    assert audit.audit_blob('ssh.pyc', marker + b'\n' + b'A' * 80)[0]['rule'] == 'private-key'
