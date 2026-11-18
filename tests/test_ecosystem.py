import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import pytest

from vox import updating
from vox.platforms import data_directory


@pytest.fixture
def signed(monkeypatch):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(updating, 'PUBLIC_KEY', base64.b64encode(public))
    payload = b'tested installer bytes'
    asset = dict(name='VoxMasterAI-9.0.0-Windows-x64-Setup.exe', size=len(payload),
                 sha256=hashlib.sha256(payload).hexdigest())
    asset['url'] = updating.RELEASES + '/download/v9.0.0/' + asset['name']
    data = dict(schema=1, version='9.0.0', minimum_version='0.1.1',
                published_at='2026-11-18', notes='测试', assets={'windows-x64-setup': asset})

    def sign(value=data):
        body = json.dumps(value).encode()
        return body, base64.b64encode(key.sign(body))
    return data, payload, sign


def test_manifest_authentication_and_tamper(signed):
    data, _, sign = signed
    body, signature = sign()
    assert updating.verify_manifest(body, signature) == data
    for changed in (body + b' ', body.replace(b'9.0.0', b'9.0.1')):
        with pytest.raises(ValueError, match='签名'):
            updating.verify_manifest(changed, signature)
    with pytest.raises(ValueError, match='签名'):
        updating.verify_manifest(body, b'not base64')


@pytest.mark.parametrize('field,value', [('url', 'https://evil.test/setup.exe'),
    ('sha256', 'no'), ('size', True), ('size', updating.MAX_PACKAGE + 1), ('name', '../setup.exe')])
def test_reject_signed_invalid_assets(signed, field, value):
    data, _, sign = signed
    data['assets']['windows-x64-setup'][field] = value
    with pytest.raises(ValueError):
        updating.verify_manifest(*sign())


def test_minimum_version_and_preview_channel(signed):
    data, _, sign = signed
    data['minimum_version'] = '8.0.0'
    with pytest.raises(ValueError, match='手动'):
        updating.verify_manifest(*sign())
    data['minimum_version'] = '0.1.1'
    data['version'] = '9.0.0rc1'
    with pytest.raises(ValueError, match='预览'):
        updating.verify_manifest(*sign())


@pytest.mark.parametrize('url', ['http://github.com/yuchen0x1/VoxMaster-AI/releases/a',
    'https://github.com.evil.test/yuchen0x1/VoxMaster-AI/releases/a',
    'https://user:pass@github.com/yuchen0x1/VoxMaster-AI/releases/a',
    'https://github.com/other/repo/releases/a', 'https://['])
def test_origin_policy(url):
    assert not updating.trusted_url(url)


def test_redirect_cannot_escape_origin(monkeypatch):
    class Response:
        status_code = 302
        headers = {'Location': 'https://evil.test/update'}
        def close(self):
            pass
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return Response()
    monkeypatch.setattr(updating.requests, 'get', get)
    with pytest.raises(ValueError, match='来源'):
        updating.response(updating.MANIFEST)
    assert calls == [updating.MANIFEST]


def test_atomic_download_cancel_corruption_and_install_recheck(signed, monkeypatch, tmp_path):
    data, payload, _ = signed
    asset = data['assets']['windows-x64-setup']
    class Response:
        body = payload
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def iter_content(self, size):
            yield self.body
    monkeypatch.setattr(updating, 'response', lambda url: Response())
    stop = threading.Event()
    dest = updating.download(asset, stop, lambda *a: None, tmp_path)
    assert dest.read_bytes() == payload
    Response.body = bytes(len(payload))
    with pytest.raises(ValueError, match='SHA-256'):
        updating.download(asset, stop, lambda *a: None, tmp_path)
    assert dest.read_bytes() == payload and not list(tmp_path.glob('*.part'))
    stop.set()
    with pytest.raises(InterruptedError):
        updating.download(asset, stop, lambda *a: None, tmp_path)
    monkeypatch.setattr(updating, 'installer_asset', lambda d: asset)
    dest.write_bytes(bytes(len(payload)))
    with pytest.raises(ValueError, match='复核'):
        updating.launch_installer(dest, data)


def test_native_data_conventions_preserve_windows():
    assert data_directory({'LOCALAPPDATA': '/local'}, 'win32', '/home') == Path('/local/VoxMasterAI')
    assert data_directory({}, 'darwin', '/home') == Path('/home/Library/Application Support/VoxMasterAI')
    assert data_directory({'XDG_DATA_HOME': '/xdg'}, 'linux', '/home') == Path('/xdg/VoxMasterAI')
    assert data_directory({'VOXMASTER_DATA': '/isolation'}, 'linux') == Path('/isolation')


def test_real_cli_render_and_no_overwrite(tmp_path):
    fixture = Path(__file__).parent / 'fixtures/fleurs-mandarin.wav'
    command = [sys.executable, 'app.py', '--cli', 'tune', str(fixture), '--output-dir', str(tmp_path)]
    completed = subprocess.run(command, capture_output=True, timeout=90)
    assert completed.returncode == 0, completed.stderr
    output = next(tmp_path.glob('*.wav'))
    before = output.read_bytes()
    repeated = subprocess.run(command, capture_output=True, timeout=90)
    assert repeated.returncode == 1 and output.read_bytes() == before


def test_cli_styles_and_report_file(tmp_path):
    fixture = Path(__file__).parent / 'fixtures/fleurs-mandarin.wav'
    listed = subprocess.run([sys.executable, 'app.py', '--cli', 'styles'],
                            capture_output=True, timeout=60)
    assert listed.returncode == 0, listed.stderr
    payload = json.loads(listed.stdout.decode('utf-8'))
    assert payload['version'] and '经典喊麦' in payload['styles']
    report = tmp_path / 'reports' / 'analysis.json'
    analyzed = subprocess.run([sys.executable, 'app.py', '--cli', 'analyze', str(fixture),
                               '--report', str(report)], capture_output=True, timeout=90)
    assert analyzed.returncode == 0, analyzed.stderr
    saved = json.loads(report.read_text('utf-8'))
    assert saved['version'] and saved['results'][0]['input'].endswith('.wav')
    assert saved['results'][0]['original']['lufs'] < 0
