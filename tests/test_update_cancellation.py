"""Cooperative cancellation stops updates before subsequent requests/publication."""
import hashlib
from threading import Event
import time

import pytest

from vox import updating
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
