from copy import deepcopy
from threading import Event

import numpy as np
import pytest

from vox.analysis import analyze
from vox.quality import assess, quality_metrics, validate_buffer
from vox.reference import comparison, describe_match, match_segments
from vox.service import measure, prepare, tuning_plan, SR
from vox.audioio import encode
from vox.storage import project


def tones(amplitude):
    t = np.arange(SR) / SR
    mono = np.concatenate([amp * np.sin(2 * np.pi * 1000 * t) for amp in amplitude]).astype("f")
    return np.column_stack((mono, mono))


def test_three_second_window_and_correlation():
    x = tones([0.1, 0.1, 0.1, 0.01, 0.01, 0.01])
    report = analyze(x, SR)
    report["segments"] = [{"start": 0.0, "end": 3.0}, {"start": 3.0, "end": 6.0}]
    q = quality_metrics(x, SR, report)
    times, levels = np.array(q["short_term_lufs"]).T
    assert list(times) == [3, 4, 5, 6]
    assert levels[0] == pytest.approx(-20, abs=0.14)
    assert levels[-1] == pytest.approx(-40, abs=0.14)
    assert report["segments"][1]["k_level"] == pytest.approx(levels[-1], abs=0.01)
    assert q["stereo_correlation"] == pytest.approx(1)
    assert quality_metrics(x[:100], SR, report)["short_term_max_lufs"] is None
    assert quality_metrics(x * [1, -1], SR, report)["stereo_correlation"] == pytest.approx(-1)
    assert quality_metrics(x * 0, SR, report)["stereo_correlation"] is None


def part(start, end, label, level=-18):
    return dict(
        start=start,
        end=end,
        label=label,
        type="未知类型",
        level_db=level,
        k_level=level,
        confidence=0.8,
        bands_db={b: -12.0 for b in ("body", "mud", "presence", "air")},
        dynamic_db=8.0,
        side_fraction=0.14,
        tail=label == "尾音",
        sustained=label == "拖腔",
        high_energy=label == "强爆发音",
    )


def test_match_uses_semantics_across_different_arrangements():
    source = dict(
        duration=20.0,
        segments=[
            part(0, 2, "普通语音"),
            part(2, 8, "强爆发音"),
            part(8, 16, "拖腔"),
            part(16, 20, "普通语音"),
        ],
    )
    target = deepcopy(source)
    target["segments"] = [
        part(0, 3, "拖腔"),
        part(3, 11, "普通语音"),
        part(11, 17, "强爆发音"),
        part(17, 20, "普通语音"),
    ]
    target["segments"][0]["bands_db"]["presence"] = -3
    target["segments"][2]["bands_db"]["presence"] = -21
    base = dict(
        automation=[dict(start=p["start"], end=p["end"]) for p in source["segments"]],
        delay=0,
        delay_type="Tempo",
    )
    result = match_segments(base, source, target)
    assert result["automation"][1]["presence_delta_db"] < 0
    assert result["automation"][2]["presence_delta_db"] > 0
    assert max(abs(row["presence_delta_db"]) for row in result["automation"]) <= 1.5
    rows = {r["role"]: r for r in comparison(source, target)}
    assert rows["拖腔"]["diff"]["presence"] == 9 and rows["尾音"].get("interval") is None
    assert "证据" in describe_match(rows["拖腔"]) and "保留" in describe_match(rows["尾音"])


def test_render_checks_and_abnormal_local_loudness():
    x = tones([0.1])
    with pytest.raises(ValueError, match="声道"):
        validate_buffer(x, len(x), 1)
    x[-1, -1] = np.nan
    with pytest.raises(ValueError, match="非有限"):
        validate_buffer(x, len(x), 2)
    before = dict(lufs=-20, short_term_lufs=[[3, -19], [4, -18], [5, -22]])
    after = dict(lufs=-19, clipped_samples=0, short_term_lufs=[[3, -18], [4, -17], [5, -35]])
    assert "短时响度" in assess(before, after, -19, {})[0]
    assert not assess(before, after, -19, {}, aligned=False)


def test_render_audit_cached_and_original_project_roundtrip(tmp_path):
    ev = Event()
    path = tmp_path / "signal.wav"
    encode(path, tones([0.1, 0.2, 0.07]), SR)
    doc = project(path)
    source = prepare(doc, ev, lambda *_: None)
    doc.update(params=tuning_plan(source.analysis), applied=True)
    tuned = prepare(doc, ev, lambda *_: None, source)
    cached = prepare(doc, ev, lambda *_: None, tuned)
    assert tuned.audit["changed_stages"] and "compression" in tuned.audit
    assert cached.audit == tuned.audit
    assert cached.output.shape == source.original.shape
    assert tuned.measured["true_peak_db"] <= doc["params"]["ceiling_db"] + 0.025
    assert source.analysis["segments"][0]["start"] == 0


def test_project_same_path_audio_replaced_while_open(tmp_path):
    path = tmp_path / "take.wav"
    replacement = tmp_path / "new.wav"
    encode(path, tones([0.05]), SR)
    doc = project(path)
    source = prepare(doc, Event(), lambda *_: None)
    encode(replacement, tones([0.4, 0.2]), SR)
    replacement.replace(path)
    new = prepare(doc, Event(), lambda *_: None, source)
    assert len(new.original) == 2 * SR
    assert new.analysis["lufs"] > source.analysis["lufs"] + 10


def test_processor_tap_uses_actual_stage_order():
    from vox.engine import process

    x = tones([0.1])
    params = tuning_plan(measure(x, Event()))
    params["disabled"] = [s for s in params["order"] if s not in ("eq", "compress")]
    seen = []
    result = process(x, SR, params, tap=lambda stage, a, b: seen.append((stage, a, b)))
    assert [s[0] for s in seen] == [s for s in params["order"] if s in ("eq", "compress")]
    np.testing.assert_array_equal(x, seen[0][1])
    np.testing.assert_array_equal(seen[0][2], seen[1][1])
    np.testing.assert_array_equal(seen[-1][2], result)


def test_native_reference_and_stage_previews(monkeypatch, tmp_path):
    from pathlib import Path
    from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QPushButton, QTabWidget
    from vox import interface, storage
    from vox.review import ReportDialog

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(interface, "ROOT", tmp_path)
    monkeypatch.setattr(storage, "ROOT", tmp_path)
    monkeypatch.setattr(interface.MainWindow, "detect", lambda self: None)
    win = interface.MainWindow()
    doc = project(Path(__file__).parent / "fixtures/fleurs-mandarin.wav")
    original = prepare(doc, Event(), lambda *_: None)
    doc.update(params=tuning_plan(original.analysis), applied=True)
    win.s = prepare(doc, Event(), lambda *_: None, original)
    report = ReportDialog(win.s, win.s.analysis, "", win)
    tabs = report.findChild(QTabWidget)
    tabs.setCurrentIndex(tabs.count() - 1)
    report.show()
    app.processEvents()
    assert not report.grab().isNull()
    choices = report.findChild(QComboBox)
    choices.setCurrentIndex(choices.findData("eq"))
    next(b for b in report.findChildren(QPushButton) if "等响试听" in b.text()).click()
    assert report.stage == "eq"
    recorded = []

    class Preview(QDialog):
        def __init__(self, buffers, levels, *args):
            super().__init__()
            recorded.append((buffers, levels))

        def exec(self):
            pass

    monkeypatch.setattr(interface, "PreviewDialog", Preview)
    monkeypatch.setattr(win, "run_job", lambda _, fn, done: done(fn(Event(), lambda *_: None)))
    win.preview_reference(1, 4, stage=report.stage)
    clean, boosted = recorded.pop()[0]
    assert clean.shape == boosted.shape and not np.array_equal(clean, boosted)
    # With the same style and no reference loaded the two renders must null.
    win.preview_reference(1, 4)
    base, matched = recorded.pop()[0]
    np.testing.assert_array_equal(base, matched)
    assert win.s.document["params"] == doc["params"]
    win.close()
