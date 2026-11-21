"""Cancellation stops pending updates without discarding published installers."""
import base64
import hashlib
import json
from pathlib import Path
from threading import Event
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from vox import update_dialog, updating
from vox.update_dialog import UpdateDialog


class Response:
    status_code = 200
    headers = {}

    def __init__(self, chunks, callback=None):
        self.chunks = chunks
        self.callback = callback
        self.closed = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def iter_content(self, _):
        for chunk in self.chunks:
            yield chunk
        if self.callback:
            self.callback()


def test_cancelled_check_makes_no_request(monkeypatch):
    cancel = Event()
    cancel.set()
    requested = []
    monkeypatch.setattr(updating, 'response', lambda url, cancel=None: requested.append(url))
    with pytest.raises(InterruptedError):
        updating.check_release(cancel)
    assert requested == []


@pytest.mark.parametrize('stage', ['manifest', 'signature'])
def test_cancelled_metadata_stops_before_signature_or_verification(monkeypatch, stage):
    cancel, requests, verified = Event(), [], []
    manifest = Response([b'{}'], cancel.set if stage == 'manifest' else None)
    signature = Response([b'signature'], cancel.set)

    def response(url, cancel=None):
        requests.append(url)
        return manifest if url == updating.MANIFEST else signature

    monkeypatch.setattr(updating, 'response', response)
    monkeypatch.setattr(updating, 'verify_manifest', lambda *args: verified.append(args))
    with pytest.raises(InterruptedError):
        updating.check_release(cancel)
    assert len(requests) == (1 if stage == 'manifest' else 2)
    assert not verified
    assert manifest.closed
    assert stage == 'manifest' or signature.closed


@pytest.mark.parametrize('operation', ['check', 'download'])
def test_cancellation_after_redirect_response_prevents_next_get(tmp_path, monkeypatch, operation):
    cancel, requests = Event(), []
    redirect = Response([])
    redirect.status_code = 302
    redirect.headers = {'Location': 'https://release-assets.githubusercontent.com/asset'}

    def get(url, **_):
        requests.append(url)
        if len(requests) == 1:
            cancel.set()
            return redirect
        return Response([b'body'])

    monkeypatch.setattr(updating.requests, 'get', get)
    with pytest.raises(InterruptedError):
        if operation == 'check':
            updating.check_release(cancel)
        else:
            updating.download(asset_for(b'body'), cancel, lambda *_: None, tmp_path)
    assert len(requests) == 1
    assert redirect.closed
    assert not list(tmp_path.glob('*.part'))


def test_uncancelled_trusted_redirect_still_works(monkeypatch):
    requests = []
    redirect, body = Response([]), Response([b'body'])
    redirect.status_code = 302
    redirect.headers = {'Location': 'https://release-assets.githubusercontent.com/asset'}

    def get(url, **_):
        requests.append(url)
        return redirect if len(requests) == 1 else body

    monkeypatch.setattr(updating.requests, 'get', get)
    with updating.response(updating.MANIFEST) as received:
        assert received is body
    assert redirect.closed and body.closed
    assert requests == [updating.MANIFEST, redirect.headers['Location']]


def asset_for(body):
    return dict(name='VoxMasterAI-Setup.exe', size=len(body),
                sha256=hashlib.sha256(body).hexdigest(),
                url=updating.RELEASES + '/download/v9.0.0/VoxMasterAI-Setup.exe')


def test_cancelled_download_does_not_create_cache_or_request(tmp_path, monkeypatch):
    cancel = Event()
    cancel.set()
    requested = []
    root = tmp_path / 'not-created'
    monkeypatch.setattr(updating, 'response', lambda url, cancel=None: requested.append(url))
    with pytest.raises(InterruptedError):
        updating.download(asset_for(b'installer'), cancel, lambda *_: None, root)
    assert requested == []
    assert not root.exists()


def test_cancel_after_last_chunk_does_not_publish_or_replace_cache(tmp_path, monkeypatch):
    body, cancel = b'verified installer bytes', Event()
    asset = asset_for(body)
    cached = tmp_path / (asset['sha256'] + '.exe')
    cached.write_bytes(b'previous cache entry')
    response = Response([body])
    monkeypatch.setattr(updating, 'response', lambda _, cancel=None: response)
    with pytest.raises(InterruptedError):
        updating.download(asset, cancel, lambda *_: cancel.set(), tmp_path)
    assert response.closed
    assert cached.read_bytes() == b'previous cache entry'
    assert list(tmp_path.iterdir()) == [cached]


def test_normal_metadata_verification_and_download_remain_available(tmp_path, monkeypatch):
    requests, verified = [], []
    release = {'version': '9.0.0'}

    def response(url, cancel=None):
        requests.append(url)
        return Response([b'{}'] if url == updating.MANIFEST else [b'c2ln\n'])

    def verify(body, signature):
        verified.append((body, signature))
        return release

    monkeypatch.setattr(updating, 'response', response)
    monkeypatch.setattr(updating, 'verify_manifest', verify)
    assert updating.check_release(Event()) is release
    assert requests == [updating.MANIFEST, updating.MANIFEST + '.sig']
    assert verified == [(b'{}', b'c2ln')]
    body = b'installer'
    monkeypatch.setattr(updating, 'response', lambda _, cancel=None: Response([body]))
    result = updating.download(asset_for(body), Event(), lambda *_: None, tmp_path)
    assert result.read_bytes() == body
    assert list(tmp_path.glob('*.part')) == []


@pytest.mark.parametrize('close_method', ['reject', 'close'])
def test_dialog_closes_after_cancelled_worker_finishes(qt_session_app, monkeypatch, close_method):
    started, release = Event(), Event()
    requested, verified = [], []

    class PausedResponse(Response):
        def iter_content(self, _):
            started.set()
            if not release.wait(3):
                raise RuntimeError('Test did not release update response')
            yield b'{}'

    def response(url, cancel=None):
        requested.append(url)
        return PausedResponse([]) if url == updating.MANIFEST else Response([b'sig'])

    monkeypatch.setattr(updating, 'response', response)
    monkeypatch.setattr(updating, 'verify_manifest', lambda *_: verified.append(True))
    dialog = UpdateDialog()
    dialog.show()
    dialog.act()
    job = dialog.job
    try:
        assert started.wait(2)
        getattr(dialog, close_method)()
        assert job.cancel.is_set()
        assert dialog.isVisible() and not dialog.action.isEnabled()
        release.set()
        assert job.wait(3000)
        deadline = time.monotonic() + 3
        while dialog.isVisible() and time.monotonic() < deadline:
            qt_session_app.processEvents()
            time.sleep(.005)
        assert not dialog.isVisible()
        assert dialog.job is None
        assert requested == [updating.MANIFEST]
        assert not verified
    finally:
        release.set()
        if dialog.job is not None:
            dialog.job.wait(3000)
        qt_session_app.processEvents()
        dialog.close()
        dialog.deleteLater()
        qt_session_app.processEvents()


@pytest.fixture
def signed_update(tmp_path, monkeypatch):
    body = b'verified installer bytes'
    asset = asset_for(body)
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    manifest = json.dumps(dict(schema=1, version='9.0.0', minimum_version='0.1.1',
                               notes='Signed notes', published_at='2026-11-21',
                               assets={'windows-x64-setup': asset})).encode()
    replies = {updating.MANIFEST: manifest, updating.MANIFEST + '.sig': base64.b64encode(key.sign(manifest)),
               asset['url']: body}
    requested = []
    installer_actions = []

    def get(url, **_):
        requested.append(url)
        return Response([replies[url]])

    monkeypatch.setattr(updating.requests, 'get', get)
    monkeypatch.setattr(updating, 'PUBLIC_KEY', base64.b64encode(public))
    # Exercise Windows update UI on every CI platform, without an installer process.
    monkeypatch.setattr(updating, 'installer_asset', lambda data: data['assets']['windows-x64-setup'])
    monkeypatch.setattr(update_dialog.QMessageBox, 'question',
                        lambda *args: installer_actions.append('confirm'))
    monkeypatch.setattr(updating, 'launch_installer', lambda *args: installer_actions.append('launch'))
    monkeypatch.setenv('VOXMASTER_DATA', str(tmp_path))
    cached = tmp_path / 'updates' / (asset['sha256'] + '.exe')
    yield body, asset, cached, replies, requested
    assert not installer_actions


@pytest.fixture
def open_update_dialog(qt_session_app):
    dialogs = []

    def open_dialog():
        dialog = UpdateDialog()
        dialogs.append(dialog)
        dialog.show()
        return dialog

    yield open_dialog
    for dialog in dialogs:
        if dialog.job is not None:
            dialog.job.cancel.set()
            dialog.job.wait(10000)
        qt_session_app.processEvents()
        dialog.close()
        dialog.deleteLater()
        qt_session_app.processEvents()


def finish_update_job(app, dialog):
    assert dialog.job is not None and dialog.job.wait(10000)
    deadline = time.monotonic() + 3
    while dialog.job is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert dialog.job is None


@pytest.mark.parametrize('close_method', ['reject', 'close'])
def test_close_after_atomic_download_keeps_committed_success(
        qt_session_app, monkeypatch, signed_update, open_update_dialog, close_method):
    body, asset, cached, _, requested = signed_update
    dialog = open_update_dialog()
    dialog.act()
    finish_update_job(qt_session_app, dialog)
    assert dialog.release is not None and dialog.package is None

    committed, unblock = Event(), Event()
    real_replace = updating.os.replace

    def replace(source, target):
        real_replace(source, target)
        if Path(target) == cached:
            committed.set()
            if not unblock.wait(10):
                raise RuntimeError('Test did not release the published download')

    monkeypatch.setattr(updating.os, 'replace', replace)
    dialog.act()
    try:
        job = dialog.job
        succeeded, cancelled, failed = [], [], []
        job.succeeded.connect(succeeded.append)
        job.cancelled.connect(lambda: cancelled.append(True))
        job.failed.connect(failed.append)
        assert committed.wait(5)
        assert cached.read_bytes() == body
        assert list(cached.parent.iterdir()) == [cached]
        getattr(dialog, close_method)()
        assert job.cancel.is_set()
        assert dialog.isVisible() and not dialog.action.isEnabled()
        unblock.set()
        finish_update_job(qt_session_app, dialog)
        assert not dialog.isVisible()
        assert requested == [updating.MANIFEST, updating.MANIFEST + '.sig', asset['url']]
        assert len(succeeded) == 1 and not cancelled and not failed
        assert dialog.package == cached
        assert dialog.progress.value() == 100
        reopened = open_update_dialog()
        reopened.act()
        finish_update_job(qt_session_app, reopened)
        assert reopened.package == cached
        assert requested == [updating.MANIFEST, updating.MANIFEST + '.sig', asset['url'],
                             updating.MANIFEST, updating.MANIFEST + '.sig']
    finally:
        unblock.set()


@pytest.mark.parametrize('case', ['valid', 'wrong-hash', 'wrong-size', 'unsigned', 'not-newer'])
def test_fresh_dialog_rechecks_signed_update_before_using_cache(
        qt_session_app, monkeypatch, signed_update, open_update_dialog, case):
    body, asset, cached, replies, requested = signed_update
    cached.parent.mkdir()
    cached.write_bytes({'wrong-hash': bytes(len(body)), 'wrong-size': body[:-1]}.get(case, body))
    if case == 'unsigned':
        replies[updating.MANIFEST] += b' '
    if case == 'not-newer':
        monkeypatch.setattr(update_dialog, '__version__', '9.0.0')

    dialog = open_update_dialog()
    dialog.act()
    finish_update_job(qt_session_app, dialog)
    assert requested == [updating.MANIFEST, updating.MANIFEST + '.sig']
    if case == 'valid':
        assert dialog.package == cached
        assert dialog.progress.value() == 100
        assert dialog.action.text() == '启动已验证的安装器'
    else:
        assert dialog.package is None
        if case in ('wrong-hash', 'wrong-size'):
            assert dialog.action.text() == '下载并校验更新'
            dialog.act()
            finish_update_job(qt_session_app, dialog)
            assert requested[-1] == asset['url'] and len(requested) == 3
            assert dialog.package == cached and cached.read_bytes() == body
        elif case == 'unsigned':
            assert '签名' in dialog.status.text() and dialog.release is None
        else:
            assert '已是最新版本' in dialog.status.text() and dialog.release is None


def test_close_ignores_queued_metadata_even_with_a_valid_cache(
        qt_session_app, signed_update, open_update_dialog):
    body, _, cached, _, requested = signed_update
    cached.parent.mkdir()
    cached.write_bytes(body)
    dialog = open_update_dialog()
    dialog.act()
    assert dialog.job.wait(10000)  # Finish the worker but leave its GUI callbacks queued.
    assert dialog.release is None and dialog.isVisible()
    dialog.reject()
    finish_update_job(qt_session_app, dialog)
    assert not dialog.isVisible()
    assert dialog.release is None and dialog.package is None
    assert requested == [updating.MANIFEST, updating.MANIFEST + '.sig']
    assert cached.read_bytes() == body


def test_close_during_cache_hash_cancels_check_without_touching_installer(
        qt_session_app, monkeypatch, signed_update, open_update_dialog):
    body, _, cached, _, requested = signed_update
    cached.parent.mkdir()
    cached.write_bytes(body)
    started, unblock = Event(), Event()
    real_open = Path.open

    class PausedFile:
        def __init__(self, source):
            self.source = source

        def __enter__(self):
            self.source.__enter__()
            return self

        def __exit__(self, *args):
            return self.source.__exit__(*args)

        def read(self, size=-1):
            chunk = self.source.read(size)
            started.set()
            if not unblock.wait(10):
                raise RuntimeError('Test did not release the cache read')
            return chunk

    def open_file(path, *args, **kwargs):
        source = real_open(path, *args, **kwargs)
        return PausedFile(source) if path == cached else source

    monkeypatch.setattr(Path, 'open', open_file)
    dialog = open_update_dialog()
    dialog.act()
    try:
        assert started.wait(5)
        qt_session_app.processEvents()
        assert dialog.isVisible() and not dialog.action.isEnabled()
        dialog.reject()
        assert dialog.job.cancel.is_set() and dialog.isVisible()
        unblock.set()
        finish_update_job(qt_session_app, dialog)
        assert not dialog.isVisible()
        assert dialog.release is None and dialog.package is None
        assert requested == [updating.MANIFEST, updating.MANIFEST + '.sig']
        assert cached.read_bytes() == body
        assert list(cached.parent.iterdir()) == [cached]
    finally:
        unblock.set()
