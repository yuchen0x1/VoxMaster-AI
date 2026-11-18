import errno
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import sounddevice as sd

from vox import audioio, models_store, playback, storage


def test_device_removed_resume_and_failed_default(monkeypatch):
    calls = []

    class Stream:
        def __init__(self, device, callback, finished_callback, **kwargs):
            self.finished = finished_callback
            self.callback = callback
            calls.append(device)

        def start(self):
            pass

        def stop(self):
            raise sd.PortAudioError("device invalidated")

        def close(self):
            self.finished()

    monkeypatch.setattr(sd, "OutputStream", Stream)
    monkeypatch.setattr(sd, "query_devices", lambda *a: {"max_output_channels": 2})
    player = playback.Playback()
    player.device = 7
    player.play(np.ones((44100, 2), "f4"), 44100, 0.2, 0.9, True)
    player._stream.callback(
        np.empty((2205, 2), "f4"), 2205, None, SimpleNamespace(output_underflow=False)
    )
    stop_at = player.position
    player._stream.finished()
    assert "默认设备" in player.poll_device()
    assert player.device is None and calls == [7, None] and player.playing
    assert player.position == stop_at and player._region == (0.2, 0.9, True)
    player._stream.finished()
    assert player.poll_device() and not player.playing
    assert player.poll_device() == "" and calls == [7, None]


def test_full_disk_and_commit_cleanup(monkeypatch, tmp_path):
    x = np.ones((4000, 2), "f4") * 0.1
    path = tmp_path / "master.wav"
    original = tmp_path / "vocal.wav"
    audioio.encode(original, x, 44100)
    samples = original.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(audioio.shutil, "disk_usage", lambda _: SimpleNamespace(free=4096))
        with pytest.raises(OSError, match="空间不足"):
            audioio.encode(path, x, 44100)

    def fail(*args):
        raise OSError(errno.ENOSPC, "ENOSPC")

    monkeypatch.setattr(audioio.os, "rename" if os.name == "nt" else "link", fail)
    with pytest.raises(OSError) as error:
        audioio.encode(path, x, 44100)
    assert error.value.errno == errno.ENOSPC
    assert list(tmp_path.iterdir()) == [original]
    assert original.read_bytes() == samples


def test_interrupted_write_preserves_checkpoint(monkeypatch, tmp_path):
    path = tmp_path / "draft.voxproj"
    doc = storage.project("old.wav", "已保存")
    storage.save_project(path, doc, backup=False)

    def fail(*args):
        raise OSError(errno.ENOSPC, "out of disk space")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError):
        storage.save_project(path, storage.project("new.wav", "新状态"), backup=False)
    assert storage.load_project(path)["name"] == "已保存"
    assert list(tmp_path.iterdir()) == [path]


def test_crash_recovery_with_relocated_audio(tmp_path):
    from vox.service import prepare

    fixture = Path(__file__).parent / "fixtures/fleurs-mandarin.wav"
    relocated = tmp_path / "搬移.wav"
    relocated.write_bytes(fixture.read_bytes())
    original = tmp_path / "导入.wav"
    relocated.rename(original)
    child = textwrap.dedent("""
        import ctypes, hashlib, os, sys, time
        from pathlib import Path
        from PySide6.QtWidgets import QApplication
        from vox.interface import MainWindow
        app = QApplication([])
        MainWindow.detect = lambda self: None
        window = MainWindow()
        def wait():
            deadline = time.monotonic() + 40
            while window.worker and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            if window.worker: raise TimeoutError()
        window.open_path(sys.argv[1])
        wait()
        window.go.click()
        wait()
        if window.s.output is None: raise ValueError("missing render")
        Path(sys.argv[2]).write_text(hashlib.sha256(window.s.output.tobytes()).hexdigest())
        if os.name == "nt":
            ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(-1), 91)
        else:
            os._exit(91)
    """)
    digest = tmp_path / "render.sha"
    env = dict(
        os.environ,
        VOXMASTER_DATA=str(tmp_path / "isolated"),
        QT_QPA_PLATFORM="offscreen",
        PYTHONFAULTHANDLER="1",
    )
    completed = subprocess.run(
        [sys.executable, "-c", child, str(original), str(digest)],
        env=env,
        timeout=75,
        capture_output=True,
    )
    assert completed.returncode == 91, completed.stderr
    recovery = list((tmp_path / "isolated/recovery").glob("*.voxproj"))
    assert len(recovery) == 1
    original.rename(relocated)
    doc = storage.load_project(recovery[0])
    assert doc["applied"] and not Path(doc["source"]).exists()
    doc["source"] = str(relocated)
    render = prepare(doc, threading.Event(), lambda *args: None)
    import hashlib

    assert hashlib.sha256(render.output.tobytes()).hexdigest() == digest.read_text()


def test_model_hash_rejects_equal_size_corruption(tmp_path, monkeypatch):
    import hashlib

    good = b"original model bytes"
    monkeypatch.setattr(
        models_store, "FILES", {"tiny.onnx": (len(good), hashlib.sha256(good).hexdigest())}
    )
    (tmp_path / "tiny.onnx").write_bytes(bytes(len(good)))
    with pytest.raises((ValueError, RuntimeError)):
        models_store.verify(tmp_path)
