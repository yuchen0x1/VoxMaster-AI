import base64
import hashlib
from pathlib import Path
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from scripts import release_assets, verify_release
from vox import updating


@pytest.fixture
def release_root(tmp_path):
    dist = tmp_path / 'dist'
    dist.mkdir()
    for name in ('VoxMasterAI-Setup.exe', 'VoxMasterAI-Portable.zip',
                 'VoxMasterAI-Source.zip', 'Qt-6.12.0-Corresponding-Sources.zip'):
        (dist / name).write_bytes(('test payload: ' + name).encode())
    notes = tmp_path / 'docs/releases/release-notes.md'
    notes.parent.mkdir(parents=True)
    notes.write_text('# Releases\n\n## 0.4.0\n\nTest notes\n', 'utf-8')
    return tmp_path


@pytest.fixture
def release_key(monkeypatch):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(updating, 'PUBLIC_KEY', base64.b64encode(public))
    return key


@pytest.mark.parametrize('with_private_file', [False, True])
def test_release_refuses_existing_staging(release_root, release_key, with_private_file):
    out = release_root / 'dist/release'
    out.mkdir()
    if with_private_file:
        (out / 'private.txt').write_bytes(b'not a release asset')
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    with pytest.raises(FileExistsError, match='already exists'):
        release_assets.prepare_release(release_root, release_key)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before
    assert not list(out.parent.glob('.vox-release-*'))


def test_release_only_publishes_explicit_assets(release_root, release_key):
    (release_root / 'dist/private.txt').write_bytes(b'not a release asset')
    out = release_assets.prepare_release(release_root, release_key)
    version = release_assets.__version__
    expected = {
        f'VoxMasterAI-{version}-Windows-x64-Setup.exe',
        f'VoxMasterAI-{version}-Windows-x64-Portable.zip',
        f'VoxMasterAI-{version}-Source-Kit.zip',
        'Qt-6.12.0-Corresponding-Sources.zip', 'update.json', 'update.json.sig', 'SHA256SUMS.txt',
    }
    assert {p.name for p in out.iterdir()} == expected
    manifest = updating.verify_manifest((out / 'update.json').read_bytes(),
                                        (out / 'update.json.sig').read_bytes())
    assert manifest['version'] == version
    assert set(manifest['assets']) == {'windows-x64-setup', 'windows-x64-portable'}
    sums = dict(line.split('  ', 1)[::-1] for line in (out / 'SHA256SUMS.txt').read_text().splitlines())
    assert set(sums) == expected - {'SHA256SUMS.txt'}
    assert all(hashlib.sha256((out / name).read_bytes()).hexdigest() == digest
               for name, digest in sums.items())
    assert not list(out.parent.glob('.vox-release-*'))


def test_release_manifest_contains_all_current_version_notes(release_root, release_key):
    notes = release_root / 'docs/releases/release-notes.md'
    notes.write_text(
        '# Releases\n\n## 0.5.3 · 2026-11-27\n\n'
        '## 📢 版本概述\n\n概述内容。\n\n'
        '## 🐛 问题修复\n\n完整修复内容。\n\n'
        '## 🧪 验证结果\n\n验证内容。\n\n'
        '## 0.5.2 · 2026-11-23\n\n旧版内容。\n',
        'utf-8',
    )

    out = release_assets.prepare_release(release_root, release_key)
    manifest = updating.verify_manifest((out / 'update.json').read_bytes(),
                                        (out / 'update.json.sig').read_bytes())

    assert '概述内容。' in manifest['notes']
    assert '完整修复内容。' in manifest['notes']
    assert '验证内容。' in manifest['notes']
    assert '旧版内容。' not in manifest['notes']


def test_notes_only_cli_needs_no_signing_key(release_root, monkeypatch):
    notes = release_root / 'docs/releases/release-notes.md'
    notes.write_text(
        '# Releases\n\n## 0.5.3 · 2026-11-27\n\n'
        '## 📢 版本概述\n\n当前正文。\n\n## 🐛 修复\n\n本次修复。\n\n'
        '## 0.5.2 · 2026-11-23\n\n历史正文。\n',
        'utf-8',
    )
    output = release_root / 'dist/release-notes.md'
    monkeypatch.setattr(release_assets, 'ROOT', release_root)
    monkeypatch.setattr(sys, 'argv', ['release_assets.py', '--notes-only', str(output)])

    release_assets.main()

    body = output.read_text('utf-8')
    assert body.startswith('## 📢 版本概述')
    assert '本次修复。' in body
    assert '历史正文。' not in body


def test_release_wrong_signing_key_cleans_only_temporary_files(release_root, release_key):
    with pytest.raises(ValueError, match='签名'):
        release_assets.prepare_release(release_root, Ed25519PrivateKey.generate())
    assert not (release_root / 'dist/release').exists()
    assert not list((release_root / 'dist').glob('.vox-release-*'))
    assert (release_root / 'dist/VoxMasterAI-Setup.exe').is_file()


def test_release_missing_input_does_not_publish_partial_directory(release_root, release_key):
    (release_root / 'dist/VoxMasterAI-Source.zip').unlink()
    with pytest.raises(FileNotFoundError):
        release_assets.prepare_release(release_root, release_key)
    assert not (release_root / 'dist/release').exists()
    assert not list((release_root / 'dist').glob('.vox-release-*'))


def test_release_preserves_destination_created_during_preparation(release_root, release_key, monkeypatch):
    verify = release_assets.verify_manifest
    out = release_root / 'dist/release'

    def competing_writer(*args):
        data = verify(*args)
        out.mkdir()
        (out / 'other.txt').write_bytes(b'preserve another writer')
        return data

    monkeypatch.setattr(release_assets, 'verify_manifest', competing_writer)
    with pytest.raises(FileExistsError, match='appeared'):
        release_assets.prepare_release(release_root, release_key)
    assert {p.name: p.read_bytes() for p in out.iterdir()} == {'other.txt': b'preserve another writer'}
    assert not list(out.parent.glob('.vox-release-*'))


def test_cached_old_manifest_cannot_verify_new_release(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['verify_release.py', '--expected-version', '0.4.0'])
    monkeypatch.setattr(updating, 'check_release', lambda: {'version': '0.3.2', 'assets': {}})
    with pytest.raises(ValueError, match='Expected published version 0.4.0, received 0.3.2'):
        verify_release.main()


@pytest.mark.parametrize('download', [False, True])
def test_exact_release_checks_links_and_optional_download(monkeypatch, download):
    asset = {'name': 'installer.exe', 'url': 'https://example.test/installer.exe', 'size': 42}
    monkeypatch.setattr(sys, 'argv', ['verify_release.py', '--expected-version', '0.4.0']
                        + (['--download'] if download else []))
    monkeypatch.setattr(updating, 'check_release',
                        lambda: {'version': '0.4.0', 'assets': {'windows-x64-setup': asset}})
    links = []
    downloads = []

    class Response:
        headers = {'Content-Length': '42'}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def response(url):
        links.append(url)
        return Response()

    monkeypatch.setattr(updating, 'response', response)
    monkeypatch.setattr(updating, 'download', lambda selected, *args: downloads.append(selected))
    verify_release.main()
    assert links == [asset['url']]
    assert downloads == ([asset] if download else [])


def test_release_workflow_does_not_publish_on_tag_push():
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/release.yml').read_text('utf-8')
    assert 'run: ./scripts/verify-release.ps1 -IsolatedRegistration' in workflow
    assert 'Stable publication requires the exact tag' in workflow
    assert '--notes-only dist/release-notes.md' in workflow
    assert '--notes-file dist/release-notes.md' in workflow
    for name in ('Prepare signed stable update assets', 'Publish explicitly approved stable release',
                 'Verify the exact published version through the public update channel'):
        step = workflow.split('- name: ' + name + '\n', 1)[1].split('\n      - ', 1)[0]
        assert "if: github.event_name == 'workflow_dispatch' && inputs.publish" in step
    assert '--expected-version $version --download' in workflow
