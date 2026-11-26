"""Metadata limits apply while bytes arrive, before a large chunk fills."""
import importlib.metadata
import json
from types import SimpleNamespace

import pytest

from vox import package_check, settings_dialog, updating, visual


class MetadataResponse:
    status_code = 200

    def __init__(self, body=b'{}', headers=None):
        self.body = body
        self.headers = headers or {}
        self.closed = False
        self.read = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def iter_content(self, size):
        self.read += 1
        yield self.body


@pytest.mark.parametrize('length', ['65537', '-1', 'invalid'])
def test_official_metadata_rejects_bad_length_before_reading(monkeypatch, length):
    response = MetadataResponse(headers={'Content-Length': length})
    monkeypatch.setattr(updating, 'response', lambda *_: response)
    with pytest.raises(ValueError, match='长度|大小限制'):
        updating.fetch(updating.MANIFEST, 65536)
    assert response.closed
    assert response.read == 0


@pytest.mark.parametrize('official', [False, True])
def test_metadata_deadline_does_not_wait_for_stream_chunk_to_fill(monkeypatch, official):
    clock = [100.0]
    consumed = []
    module = updating if official else settings_dialog
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])

    class TricklingResponse(MetadataResponse):
        def iter_content(self, size):
            buffered = bytearray()
            for byte in b' ' * 100 + b'{"version":"99.0.0"}':
                clock[0] += 5
                consumed.append(byte)
                buffered.append(byte)
                if len(buffered) >= size:
                    yield bytes(buffered)
                    buffered.clear()
            if buffered:
                yield bytes(buffered)

    response = TricklingResponse()
    if official:
        monkeypatch.setattr(updating, 'response', lambda *_: response)
        check = lambda: updating.fetch(updating.MANIFEST, 65536)
    else:
        monkeypatch.setattr(settings_dialog.requests, 'get', lambda *_a, **_k: response)
        check = lambda: settings_dialog.check_version('https://example.test/version')
    with pytest.raises(TimeoutError, match='超时'):
        check()
    assert response.closed
    assert len(consumed) <= 6


def test_official_metadata_still_accepts_complete_response(monkeypatch):
    response = MetadataResponse(b'{"schema":1}', {'Content-Length': '12'})
    monkeypatch.setattr(updating, 'response', lambda *_: response)
    assert updating.fetch(updating.MANIFEST, 65536) == response.body
    assert response.closed


@pytest.mark.parametrize('platform,expected', [
    ('win32', 'onnxruntime-directml'), ('linux', 'onnxruntime'), ('darwin', 'onnxruntime'),
])
def test_package_diagnostic_uses_platform_runtime_distribution(
        tmp_path, monkeypatch, qt_session_app, platform, expected):
    queried = []

    def version(package):
        queried.append(package)
        if package.startswith('onnxruntime'):
            raise RuntimeError('Stopped after recording runtime distribution')
        return 'test'

    monkeypatch.setattr(importlib.metadata, 'version', version)
    monkeypatch.setattr(package_check, 'sys', SimpleNamespace(platform=platform))
    monkeypatch.setattr(visual, 'app_icon', lambda: SimpleNamespace(isNull=lambda: False))
    report = tmp_path / 'diagnostic.json'
    assert package_check.main([str(report)]) == 1
    assert queried[-1] == expected
    assert 'Stopped after recording runtime distribution' in json.loads(
        report.read_text('utf-8'))['error']
