"""Desktop routing tests; DSP and real inference are verified in separate suites."""

import copy
from dataclasses import replace
from pathlib import Path
import time

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QCoreApplication
from PySide6.QtWidgets import QMessageBox

from vox import interface, song, storage
from vox.dialogs import ParameterDialog, managed_dialog
from vox.song_dialog import FIELDS, SongDialog

SPEECH = Path(__file__).parent / "fixtures" / "fleurs-mandarin.wav"


def settle(app, window):
    deadline = time.monotonic() + 90
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert window.worker is None, "Worker did not finish in 90 seconds"
    assert not window.test_errors, window.test_errors


@pytest.fixture
def window(tmp_path, monkeypatch, qt_session_app):
    monkeypatch.setattr(storage, "ROOT", tmp_path)
    monkeypatch.setattr(interface, "ROOT", tmp_path)
    monkeypatch.setattr(interface.MainWindow, "detect", lambda self: None)
    result = interface.MainWindow()
    result.test_errors = []
    monkeypatch.setattr(result, "notice", result.test_errors.append)
    result.timer.stop()
    result.show()
    qt_session_app.processEvents()
    yield result
    if result.worker is not None:
        result.cancel()
        settle(qt_session_app, result)
    result.close()
    result.deleteLater()
    for _ in range(2):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_session_app.processEvents()


def test_blank_mode_guides_and_persists_through_import(window, qt_session_app):
    assert set(window.mode_buttons) == {"vocal", "song", "multitrack"}
    for mode in window.mode_buttons:
        assert window.mode_buttons[mode].objectName() == "mode_" + mode
    window.mode_buttons["song"].click()
    assert window.go.text() == "整曲处理…"
    assert "分轨" in window.mode_hint.text()
    window.open_path(SPEECH)
    settle(qt_session_app, window)
    assert window.mode() == "song" and window.s.output is None
    assert storage.load_project(window.last_autosave)["mode"] == "song"
    assert "song" not in window.s.document
    window.mode_buttons["multitrack"].click()
    settle(qt_session_app, window)
    assert window.mode() == "multitrack"
    assert window.go.text() == "打开多轨工作室"
    assert "手动管理轨道" in window.mode_hint.text()


def test_mode_is_explicit_on_vocal_import(window, qt_session_app):
    window.open_path(SPEECH)
    settle(qt_session_app, window)
    assert window.s.document["mode"] == "vocal"
    assert window.style.isVisible() and window.kind.isVisible()
    assert window.mode_buttons["vocal"].isChecked()


def test_route_does_not_clear_current_output_or_song_stems(window, qt_session_app):
    window.open_path(SPEECH)
    settle(qt_session_app, window)
    window.go.click()
    settle(qt_session_app, window)
    original = window.s.output.copy()
    params = copy.deepcopy(window.s.document["params"])
    for mode in ("multitrack", "song", "vocal"):
        window.mode_buttons[mode].click()
        settle(qt_session_app, window)
        assert window.mode() == mode
        np.testing.assert_array_equal(window.s.output, original)
        assert window.s.document["params"] == params


def test_full_song_calls_shared_separation_and_plan(window, monkeypatch, qt_session_app, tmp_path):
    destination = tmp_path / "outputs"
    captured = {}
    monkeypatch.setattr(window, "separation_model_ready", lambda: True)
    monkeypatch.setattr(window, "separation_destination", lambda: str(destination))
    window.import_mode = "song"
    window.open_path(SPEECH)
    settle(qt_session_app, window)

    def separate_project(current, destination, cancel, progress, **kwargs):
        captured.update(destination=destination, **kwargs)
        return current

    def confirm(dialog):
        dialog.target.setCurrentIndex(dialog.target.findData("impact"))
        dialog.master.setCurrentIndex(dialog.master.findData("strong"))
        return 1

    monkeypatch.setattr(interface.service, "separate_project", separate_project)
    monkeypatch.setattr(SongDialog, "exec", confirm)
    window.song_mix()
    settle(qt_session_app, window)
    assert captured["destination"] == str(destination)
    assert captured["song_options"]["target"] == "impact"
    assert captured["song_options"]["master"] == "strong"
    assert "plan" not in captured["song_options"]


def test_resolved_plan_round_trips_and_can_be_edited(window):
    assert set(FIELDS) == {"vocal_gain_db", "instrumental_gain_db", "instrumental_low_db",
                          "instrumental_mid_db", "instrumental_high_db", "target_lufs", "ceiling_db"}
    initial = SongDialog(list(interface.engine.PRESETS), "经典喊麦", has_stems=True,
                         plan={"target": "forward", "master": "custom", "vocal_gain_db": 2.5,
                               "ceiling_db": -1.1}, parent=window)
    with managed_dialog(initial):
        assert initial.reviewing and initial.values["vocal_gain_db"].value() == 2.5
        assert initial.options()["plan"] == initial.plan
        initial.values["vocal_gain_db"].setValue(3.5)
        options = initial.options()
    assert options["target"] == "custom"
    assert options["plan"]["vocal_gain_db"] == 3.5
    assert options["plan"]["ceiling_db"] == -1.1
    assert song.validate_plan(options["plan"]) == options["plan"]


def test_review_does_not_discard_vocal_params_or_rerun_analysis(window, monkeypatch, qt_session_app):
    # This routing test supplies synthetic stem paths; media identity is covered
    # separately by test_commit_media_identity.py.
    monkeypatch.setattr(interface.service, "verify_session_media", lambda session: None)
    window.open_path(SPEECH)
    settle(qt_session_app, window)
    params = copy.deepcopy(window.current_params())
    window.s.sources["Instrumental"] = np.zeros_like(window.s.original)
    window.s.document.update(
        mode="song", stems={"Vocal": "/stems/vocal.wav", "Instrumental": "/stems/music.wav"},
        song=song.validate_plan({}), params=params, applied=True,
    )
    window.refresh()
    calls = []

    def plan_song(current, cancel, progress, **options):
        calls.append((copy.deepcopy(current.document["params"]), options))
        return current

    def confirm(dialog):
        dialog.values["target_lufs"].setValue(-13.0)
        return 1

    monkeypatch.setattr(interface.service, "plan_song", plan_song)
    monkeypatch.setattr(SongDialog, "exec", confirm)
    window.song_mix()
    settle(qt_session_app, window)
    assert window.go.text() == "复核整曲方案…"
    assert len(calls) == 1 and calls[0][0] == params
    options = calls[0][1]
    assert options["target"] == "natural" and options["master"] == "conservative"
    assert options["plan"]["target_lufs"] == -13.0


@pytest.mark.parametrize("master", ["standard", "strong"])
def test_manual_ceiling_edit_preserves_selected_mastering_strength(window, master):
    initial = SongDialog(list(interface.engine.PRESETS), "经典喊麦", has_stems=True,
                         plan=song.validate_plan({"target": "forward", "master": master}),
                         parent=window)
    with managed_dialog(initial):
        initial.values["ceiling_db"].setValue(-1.3)
        options = initial.options()

    assert options["master"] == master
    assert options["plan"]["master"] == master
    assert options["target"] == "forward"
    assert options["plan"]["ceiling_db"] == -1.3


def test_explicit_reseparate_clears_song_plan_without_silent_timeline_overwrite(window, monkeypatch,
                                                                           qt_session_app, tmp_path):
    # This routing test returns a synthetic Session; real media identity checks
    # are covered separately by test_commit_media_identity.py.
    monkeypatch.setattr(interface.service, "verify_session_media", lambda session: None)
    window.open_path(SPEECH)
    settle(qt_session_app, window)
    window.s.document["stems"] = {"Vocal": "/stems/vocal.wav", "Instrumental": "/stems/music.wav"}
    window.s.document["song"] = song.validate_plan({})
    window.s.document["studio"] = {"schema": 1}
    monkeypatch.setattr(window, "separation_model_ready", lambda: True)
    monkeypatch.setattr(window, "separation_destination", lambda: str(tmp_path))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    calls = []

    def separate_project(current, destination, cancel, progress, **options):
        calls.append(options)
        document = copy.deepcopy(current.document)
        document.pop("song")
        document["studio"] = None
        return replace(current, document=document)

    monkeypatch.setattr(interface.service, "separate_project", separate_project)
    window.separate()
    assert calls == []
    assert "song" in window.s.document and window.s.document["studio"] is not None
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    window.separate()
    settle(qt_session_app, window)
    assert calls == [{"song_options": None}]
    assert "song" not in window.s.document and window.s.document["studio"] is None


def test_primary_routes_by_mode_and_vocal_rerender_is_undoable(window, monkeypatch, qt_session_app):
    window.open_path(SPEECH)
    settle(qt_session_app, window)
    window.go.click()
    settle(qt_session_app, window)
    tuned = window.s.output.copy()

    def edit(dialog):
        dialog.inputs["target_lufs"].setValue(-21.0)
        return 1

    monkeypatch.setattr(ParameterDialog, "exec", edit)
    window.parameters()
    settle(qt_session_app, window)
    edited = window.s.output.copy()
    assert not np.array_equal(edited, tuned)
    window.travel(False)
    settle(qt_session_app, window)
    np.testing.assert_array_equal(window.s.output, tuned)
    window.travel(True)
    settle(qt_session_app, window)
    np.testing.assert_array_equal(window.s.output, edited)
    for mode in ("song", "vocal", "multitrack"):
        window.mode_buttons[mode].click()
        settle(qt_session_app, window)
        np.testing.assert_array_equal(window.s.output, edited)
