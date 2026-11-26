"""Keep the desktop transport in sync when PortAudio finishes between ticks."""

from types import SimpleNamespace

import numpy as np
import pytest
import sounddevice as sd

from vox import interface, storage


@pytest.fixture
def window(tmp_path, monkeypatch, qt_session_app):
    class Stream:
        def __init__(self, callback, finished_callback, **kwargs):
            self.callback = callback
            self.finished = finished_callback

        def start(self):
            pass

        def stop(self):
            self.finished()

        def close(self):
            pass

    monkeypatch.setattr(sd, "query_devices", lambda *args: {"max_output_channels": 2})
    monkeypatch.setattr(sd, "OutputStream", Stream)
    monkeypatch.setattr(storage, "ROOT", tmp_path)
    monkeypatch.setattr(interface, "ROOT", tmp_path)
    monkeypatch.setattr(interface.MainWindow, "detect", lambda self: None)
    result = interface.MainWindow()
    result.timer.stop()
    result.s = SimpleNamespace(original=np.zeros((4410, 2), dtype="f"), output=None)
    qt_session_app.processEvents()
    yield result
    result.close()
    result.deleteLater()
    qt_session_app.processEvents()


def advance(player, frames):
    player._stream.callback(
        np.empty((frames, 2), dtype="f"), frames, None,
        SimpleNamespace(output_underflow=False),
    )


def test_natural_completion_releases_stream_and_next_play_restarts(window):
    window.play()
    advance(window.player, 4000)
    window.tick()
    assert 0 < window.cursor < 0.1
    stream = window.player._stream
    with pytest.raises(sd.CallbackStop):
        advance(window.player, 1024)
    stream.finished()

    window.tick()

    assert window.cursor == 0.1
    assert window.timeline.cursor == 0.1
    assert window.player._stream is None
    window.play()
    assert window.player.position == 0
    assert window.player.playing


def test_seek_before_completion_tick_keeps_requested_position(window):
    window.play()
    advance(window.player, 4000)
    window.tick()
    with pytest.raises(sd.CallbackStop):
        advance(window.player, 1024)
    window.player._stream.finished()

    window.seek(0.025)

    assert window.cursor == 0.025
    assert window.timeline.cursor == 0.025
    assert not window.player.playing
    window.play()
    assert window.player.position == pytest.approx(0.025, abs=1 / 44100)


def test_play_before_completion_tick_restarts_from_zero(window):
    window.play()
    advance(window.player, 4000)
    window.tick()
    with pytest.raises(sd.CallbackStop):
        advance(window.player, 1024)
    window.player._stream.finished()

    window.play()

    assert window.player.position == 0
    assert window.player.playing


def test_manual_pause_preserves_position_for_resume(window):
    window.play()
    advance(window.player, 1764)
    window.play()

    assert not window.player.playing
    assert window.cursor == 0.04
    window.play()
    assert window.player.position == 0.04
    assert window.player.playing
