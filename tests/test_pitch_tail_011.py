import os
import time
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from scipy import signal

from vox import engine
from vox.analysis import pitch_track
from vox.tail011 import slice_params, stretch, validate_edits

SR = 16000


def tone(f, seconds, rate=SR):
    t = np.arange(round(rate * seconds)) / rate
    return (
        0.18 * np.sin(2 * np.pi * f * t) * signal.windows.tukey(len(t), 0.06)
    ).astype("f")[:, None]


def isolated(stage, **changes):
    return dict(
        engine.PRESETS["经典喊麦"],
        disabled=[s for s in engine.STAGES if s != stage],
        **changes,
    )


def tail(**changes):
    return dict(
        {
            "start": 0.28,
            "end": 0.58,
            "stretch": 1.0,
            "repeats": 5,
            "delay": 0.45,
            "reverb": 0.0,
            "gain_db": 0.0,
        },
        **changes,
    )


def edit(**changes):
    return dict(
        {"start": 0.17, "end": 0.79, "strength": 0.0, "speed_ms": 20, "semitones": 2.0},
        **changes,
    )


def test_unvoiced_and_speech_gate_with_manual_override():
    x = tone(196, 1)
    base = isolated(
        "pitch",
        pitch_strength=0.9,
        semitones=1.0,
        automation=[{"start": 0.0, "end": 1.0, "pitch_safe": False}],
    )
    assert np.array_equal(engine.process(x, SR, base), x)
    manual = engine.process(x, SR, dict(base, pitch_regions=[edit()]))
    assert np.array_equal(manual[: round(0.17 * SR)], x[: round(0.17 * SR)])
    assert np.array_equal(manual[round(0.79 * SR) :], x[round(0.79 * SR) :])
    _, hz = pitch_track(manual[SR // 3 : 2 * SR // 3], SR)
    assert abs(np.median(hz[hz > 0]) - 196 * 2 ** (2 / 12)) < 2.0
    silence = x * 0
    assert np.array_equal(
        engine.process(silence, SR, dict(base, pitch_regions=[edit()])), silence
    )


def test_register_transition_and_noise_consonant_preserved():
    rng = np.random.default_rng(55)
    x = np.vstack(
        (tone(164, 0.45), tone(328, 0.45), rng.normal(0, 0.02, (3000, 1)).astype("f"))
    )
    p = isolated("pitch", pitch_strength=1.0, semitones=2.0)
    y = engine.process(x, SR, p)
    a = round(0.45 * SR)
    assert np.max(abs(y[a - 60 : a + 60] - x[a - 60 : a + 60])) < 0.002
    assert np.array_equal(y[-1800:], x[-1800:])
    _, hz, confidence = pitch_track(x, SR, return_confidence=True)
    assert np.max(confidence) > 0.98 and np.all(confidence[hz == 0] == 0)


def test_tail_detection_and_next_phrase_guard():
    x = np.vstack(
        (
            tone(208, 0.58),
            np.zeros((SR // 4, 1), "f"),
            tone(305, 0.6),
            np.zeros((SR // 3, 1), "f"),
        )
    )
    r = engine.analyze(x, SR)
    candidate = next(k for k in r["tail_candidates"] if k["candidate"])
    assert (
        abs(candidate["end"] - 0.58) <= 0.025
        and abs(candidate["next_start"] - 0.83) <= 0.025
    )
    assert candidate["sustained"]
    p = isolated(
        "space",
        reverb=0.0,
        tail_regions=[tail()],
        tail_times=[],
        delay_ms=210,
        feedback=0.7,
        delay_type="Ping-Pong",
    )
    for mode in ("Stereo", "Ping-Pong", "Tempo"):
        y = engine.process(x, SR, dict(p, delay_type=mode))
        assert np.array_equal(y[round(0.83 * SR) :], x[round(0.83 * SR) :])
    wet = engine.process(x, SR, p) - x
    assert np.max(np.abs(wet[round(0.59 * SR) : round(0.80 * SR)])) > 0.04
    quiet = engine.process(x, SR, dict(p, tail_regions=[tail(repeats=0)]))
    np.testing.assert_array_equal(quiet, x)


@pytest.mark.parametrize("ratio", [0.65, 1.65])
def test_wsola_tail_duration_preserves_frequency_and_other_samples(ratio):
    sample = tone(203.5, 0.36)
    n = round(len(sample) * ratio)
    y = stretch(sample, SR, n)
    assert len(y) == n
    _, hz = pitch_track(y, SR)
    assert abs(np.median(hz[hz > 0]) - 203.5) < 3
    x = np.vstack((tone(203.5, 0.58), np.zeros((SR, 1), "f")))
    p = isolated(
        "space",
        reverb=0.0,
        tail_regions=[tail(stretch=ratio, delay=0.0)],
        tail_times=[],
    )
    result = engine.process(x, SR, p)
    assert len(result) == len(x) and np.array_equal(
        result[: int(0.28 * SR)], x[: int(0.28 * SR)]
    )
    end = round((0.28 + 0.30 * ratio) * SR)
    assert np.max(np.abs(result[end - 500 : end])) > 0.025
    assert np.max(np.abs(result[end:])) < 1e-6


def test_rebasing_and_intersecting_preview_regions():
    p = {
        "tail_times": [1.0, 7.2, 9.0],
        "pitch_regions": [edit(start=6.0, end=8.0)],
        "automation": [
            {
                "start": 2.0,
                "end": 9.0,
                "next_start": 9.5,
                "tail_regions": [tail(start=7.5, end=8.5)],
            }
        ],
    }
    before = deepcopy(p)
    clipped = slice_params(p, 7, 8.4)
    np.testing.assert_allclose(clipped["tail_times"], [0.2])
    assert (
        clipped["pitch_regions"][0]["start"] == 0
        and clipped["pitch_regions"][0]["end"] == 1
    )
    assert clipped["automation"][0]["next_start"] is None
    assert abs(clipped["automation"][0]["tail_regions"][0]["end"] - 1.4) < 1e-6
    assert p == before
    with pytest.raises(ValueError):
        validate_edits({"tail_regions": [tail(), tail(start=0.45)]})


def test_true_speech_manual_edit_leaves_consonants_outside_selection():
    from vox.audioio import decode

    x, _ = decode(Path(__file__).parent / "fixtures" / "fleurs-mandarin.wav")
    t, hz = pitch_track(x, 44100)
    voiced = hz > 0
    spans = np.flatnonzero(np.diff(voiced.astype(int), prepend=0, append=0)).reshape(
        -1, 2
    )
    i, j = max(spans, key=lambda pair: pair[1] - pair[0])
    a, b = t[i], t[j - 1]
    p = isolated("pitch", pitch_regions=[edit(start=a, end=b)])
    y = engine.process(x, 44100, p)
    assert np.array_equal(y[: round(a * 44100)], x[: round(a * 44100)])
    assert np.array_equal(y[round(b * 44100) + 1 :], x[round(b * 44100) + 1 :])
    assert np.max(np.abs(y - x)) > 1e-4


def test_native_curve_selection_commit_undo_and_measured_ab(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from vox.dialogs import ParameterDialog

    app = QApplication.instance() or QApplication([])
    x = np.vstack((tone(196, 0.95), np.zeros((SR // 3, 1), "f"), tone(245, 0.5)))
    base = isolated("pitch", pitch_strength=0.0)
    dlg = ParameterDialog(
        base, len(x) / SR, audio=x, sr=SR, report=engine.analyze(x, SR)
    )
    editor = dlg.phrase_editor
    dlg.tabs.setCurrentWidget(editor)
    dlg.show()
    app.processEvents()
    try:
        plot = editor.plot
        QTest.mousePress(plot, Qt.LeftButton, pos=QPoint(round(plot.xpos(0.15)), 40))
        QTest.mouseRelease(plot, Qt.LeftButton, pos=QPoint(round(plot.xpos(0.82)), 40))
        assert 0.13 < editor.begin.value() < 0.17 and 0.80 < editor.end.value() < 0.84
        editor.pitch.setValue(2.0)
        editor.commit("pitch_regions")
        assert dlg.value()["pitch_regions"][0]["semitones"] == 2
        delivered = []
        monkeypatch.setattr(editor, "play", lambda buf: delivered.append(buf.copy()))
        editor.audition(False)
        editor.audition(True)
        deadline = time.monotonic() + 8
        while editor.worker and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert len(delivered) == 2
        assert np.max(np.abs(delivered[1] - delivered[0])) > 0.05
        assert (
            editor.plot.after.shape[1] == 2
            and np.count_nonzero(editor.plot.after[:, 1]) > 8
        )
        editor.undo()
        assert dlg.value()["pitch_regions"] == []
        editor.on_candidate(1)
        editor.stretch.setValue(1.4)
        editor.commit("tail_regions")
        assert dlg.value()["tail_regions"][0]["stretch"] == 1.4
        editor.audition(True, next_phrase=True)
        while editor.worker and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert len(delivered) == 3
    finally:
        dlg.reject()
        dlg.close()
