import tempfile
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from vox import audioio, settings_dialog
from vox.hardware import resolve_output
from vox.playback import Playback


def test_directory_routing_and_settings(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    report = {"devices": [{"id": 5, "outputs": 2, "inputs": 0, "host": "WASAPI", "name": "USB"}]}
    old = {
        "output_device": 2,
        "output_device_name": "USB",
        "output_device_host": "WASAPI",
        "recent": ["a"],
    }
    dlg = settings_dialog.SettingsDialog(old, report)
    assert resolve_output(old, report) == 5
    dlg._paths["cache_dir"].setText(str(tmp_path / "缓存"))
    dlg.accept()
    cfg = dlg.value()
    assert (
        dlg.result() == dlg.DialogCode.Accepted
        and cfg["output_device"] == 5
        and cfg["recent"] == ["a"]
    )
    assert Path(cfg["cache_dir"]).is_dir()
    monkeypatch.setattr(audioio, "_SPOOL_BYTES", 8)
    monkeypatch.setattr(audioio, "_cache_directory", None)
    audioio.set_cache_directory(cfg["cache_dir"])
    used = []
    original = tempfile.SpooledTemporaryFile

    def capture(**kwargs):
        used.append(kwargs["dir"])
        return original(**kwargs)

    monkeypatch.setattr(audioio.tempfile, "SpooledTemporaryFile", capture)
    pcm = np.full((4410, 2), 0.25, dtype=np.float32)
    path = tmp_path / "试听.wav"
    audioio.encode(path, pcm, 44100, 32)
    array, _ = audioio.decode(path)
    assert used == [Path(cfg["cache_dir"])] and np.array_equal(array, pcm)
    dlg.close()
    app.processEvents()


def test_unavailable_endpoint_and_malformed_url():
    assert resolve_output({"output_device": 3}, {"devices": []}) is None
    for url in ("https://[", "file:///disk", "https://name:pass@files.test/"):
        with pytest.raises(ValueError):
            settings_dialog.check_version(url)


def test_update_manifest(monkeypatch):
    class Response:
        status_code = 200
        body = b'{"version":"0.3.0"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_content(self, size):
            yield self.body

    monkeypatch.setattr(settings_dialog.requests, "get", lambda *args, **kwargs: Response())
    assert "0.3.0" in settings_dialog.check_version("https://release.test/version")
    Response.body = b"x" * 65537
    with pytest.raises(ValueError):
        settings_dialog.check_version("https://release.test/version")


def test_transport_pcm(monkeypatch):
    import sounddevice as sd

    class Status:
        output_underflow = False

    class Stream:
        def __init__(self, callback, finished_callback, **kw):
            self.callback = callback
            self.finished = finished_callback

        def start(self):
            pass

        def close(self):
            pass

        def stop(self):
            self.finished()

    monkeypatch.setattr(sd, "query_devices", lambda *a: {"max_output_channels": 2})
    monkeypatch.setattr(sd, "OutputStream", Stream)
    p = Playback()
    samples = np.ones((44100, 2), "f4") * [0.2, 0.4]
    p.volume = 0.5
    p.play(samples, 44100, start=0.25, end=0.26, loop=True)
    buf = np.zeros((1000, 2), dtype="f4")
    p._stream.callback(buf, len(buf), None, Status())
    np.testing.assert_allclose(buf[190], [0.1, 0.2])
    assert 0.25 <= p.position < 0.26
    p.play(samples, 44100)
    p._stream.callback(buf, len(buf), None, Status())
    assert not p.replace_buffer(samples[:12])
    assert p.replace_buffer(np.zeros_like(samples))
    p._stream.callback(buf, len(buf), None, Status())
    np.testing.assert_allclose(buf[0], [0.1, 0.2])
    assert 0 < buf[66, 0] < 0.1 and buf[135, 0] == 0
    p.pause()
    assert not p.playing and p.position > 0
    p.stop()
    assert p.position == 0
