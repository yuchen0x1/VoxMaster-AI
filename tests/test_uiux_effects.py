"""Focused Qt widget contracts for effect editing and its reports; no media I/O."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
)

from vox.dialogs import ExportDialog, ParameterDialog
from vox.dsp_panel import EqEditor, Trace
from vox.engine import normalize
from vox.pitch_tail_editor import PitchCanvas
from vox.presets import DEFAULT
from vox.review import PreviewDialog, ReportDialog, TracePlot
from vox.song_dialog import SongDialog
from vox.theme import COLORS, manager


@pytest.fixture
def appearance(qt_session_app):
    theme = manager(qt_session_app)
    previous = theme.mode
    yield theme
    theme.set_mode(previous)


def _has_label(widget, root):
    return bool(widget.accessibleName()) and any(
        label.buddy() is widget for label in root.findChildren(QLabel)
    )


def test_same_canvases_paint_both_themes(appearance):
    appearance.set_mode("light")
    dialog = ParameterDialog(DEFAULT, 2)
    plots = (
        dialog.findChild(EqEditor),
        PitchCanvas([(0.1, 110), (0.5, 142)], 2),
        Trace("原音基频 · Hz"),
        TracePlot([[-12, -6]], ["A", "B"]),
    )
    try:
        for mode in ("light", "dark", "light"):
            appearance.set_mode(mode)
            for plot in plots:
                plot.resize(340, 230)
                # Sample the unobstructed border of the actual painted widget.
                image = plot.grab().toImage()
                assert image.pixelColor(0, 0).name() == COLORS[mode]["canvas"].lower()
                assert plot.accessibleName()
                assert plot.focusPolicy() == Qt.NoFocus
    finally:
        dialog.deleteLater()
        for plot in plots[1:]:
            plot.deleteLater()


def test_chain_buttons_preserve_check_state_and_serialization(appearance):
    appearance.set_mode("light")
    dialog = ParameterDialog(dict(DEFAULT, disabled=["pitch"]), 2, tab=1)
    try:
        up = next(b for b in dialog.findChildren(QPushButton) if b.text() == "上移")
        down = next(b for b in dialog.findChildren(QPushButton) if b.text() == "下移")
        assert up.focusPolicy() & Qt.TabFocus
        assert up.accessibleName() and down.accessibleName()
        original = dialog.value()["order"]
        up.click()  # First row cannot move upward.
        assert dialog.value()["order"] == original
        dialog.chain.setCurrentRow(1)
        up.click()
        changed = dialog.value()
        assert dialog.chain.currentItem().data(Qt.UserRole) == "pitch"
        assert dialog.chain.currentItem().checkState() == Qt.Unchecked
        assert normalize(changed)["order"] == [original[1], original[0], *original[2:]]
        assert changed["disabled"] == ["pitch"]
        down.click()
        assert dialog.value()["order"] == original
        dialog.inputs["body_hz"].setValue(187)
        assert dialog.value()["body_hz"] == 187
        assert _has_label(dialog.inputs["body_hz"], dialog)
        assert _has_label(dialog.enums["hum_hz"], dialog)
        assert _has_label(dialog.time, dialog)
    finally:
        dialog.deleteLater()


def test_long_effect_pages_and_numeric_edits(appearance):
    appearance.set_mode("light")
    sr = 44100
    dialog = ParameterDialog(
        dict(DEFAULT, automation=[{"start": 0.1, "end": 0.8}]), 2,
        audio=np.zeros((2 * sr, 1), dtype=np.float32), sr=sr, report={},
    )
    editor = dialog.phrase_editor
    automation = dialog.automation_page
    try:
        dialog.resize(420, 320)
        dialog.tabs.setCurrentWidget(editor)
        dialog.show()
        appearance.app.processEvents()
        assert dialog.width() == 420 and dialog.height() == 320
        assert editor.scroll.verticalScrollBar().maximum() > 0
        assert editor.scroll.horizontalScrollBar().maximum() == 0
        assert isinstance(dialog.tabs.widget(dialog.tabs.count() - 1), QScrollArea)
        assert _has_label(editor.begin, editor)
        assert _has_label(editor.end, editor)
        assert _has_label(editor.pitch, editor)
        assert _has_label(dialog.meters.start, dialog.meters)
        assert _has_label(automation.inputs["body_delta_db"], automation)
        editor.begin.setValue(0.1)
        editor.end.setValue(0.8)
        editor.pitch.setValue(2.0)
        assert editor.plot.range == (0.1, 0.8)
        editor.commit("pitch_regions")
        assert dialog.value()["pitch_regions"][0]["semitones"] == 2
        editor.undo()
        assert dialog.value()["pitch_regions"] == []
    finally:
        dialog.reject()
        dialog.deleteLater()


def test_report_long_evidence_is_scrollable_and_selectable(appearance):
    appearance.set_mode("light")
    evidence = "\n".join(f"检测信息 {i} " + "较长的证据描述 " * 12 for i in range(60))
    summary = "可复制的音频体检\n" + evidence
    parts = [{"start": 0.1, "end": 0.8, "evidence": [evidence], "limitations": ["限制"]}]
    session = SimpleNamespace(audit={}, analysis={}, measured=None)
    dialog = ReportDialog(session, {"segments": parts}, summary, None)
    try:
        dialog.resize(420, 320)
        tabs = dialog.findChild(QTabWidget)
        text = tabs.widget(0)
        assert text.isReadOnly()
        text.selectAll()
        assert text.textCursor().selectedText().replace("\u2029", "\n") == summary
        tabs.setCurrentIndex(1)
        dialog.show()
        appearance.app.processEvents()
        assert dialog.width() == 420 and dialog.height() == 320
        area = tabs.currentWidget()
        assert isinstance(area, QScrollArea)
        detail = area.findChild(QPlainTextEdit)
        assert detail.isReadOnly()
        assert detail.toPlainText() == evidence + "\n限制"
        assert detail.verticalScrollBar().maximum() > 0
        assert dialog.interval == (0.1, 0.8)
    finally:
        dialog.reject()
        dialog.deleteLater()


def test_tab_bars_keep_every_caption_reachable(appearance):
    appearance.set_mode("light")
    dialog = ParameterDialog(
        dict(DEFAULT, automation=[{"start": 0.1, "end": 0.8}]), 2,
        audio=np.zeros((2 * 44100, 1), dtype=np.float32), sr=44100, report={},
    )
    try:
        dialog.resize(560, 610)
        dialog.show()
        appearance.app.processEvents()
        bar = dialog.tabs.tabBar()
        assert dialog.tabs.count() == 7
        assert bar.elideMode() == Qt.TextElideMode.ElideNone
        assert dialog.tabs.usesScrollButtons()
        assert bar.count() == 7
        # Every caption keeps its full requested width; overflow scrolls, never clips.
        widths = [bar.tabRect(index).width() for index in range(bar.count())]
        for index, width in enumerate(widths):
            assert width >= bar.fontMetrics().horizontalAdvance(bar.tabText(index)) + 16
        scrollers = [w for w in bar.children() if w.isVisible() and w.width() <= 30]
        if sum(widths) > bar.width():
            assert scrollers
            dialog.tabs.setCurrentIndex(6)
            appearance.app.processEvents()
            last = bar.tabRect(6)
            assert last.left() >= 0 and last.right() <= bar.width()
        else:
            # Narrow system fonts fit all captions: Qt then creates no scroller,
            # and every tab must be fully visible inside the bar.
            assert all(bar.tabRect(i).right() <= bar.width() for i in range(bar.count()))
    finally:
        dialog.reject()
        dialog.deleteLater()


def test_song_dialog_follows_content_height(appearance):
    appearance.set_mode("dark")
    plan = {"target": "natural", "master": "conservative"}
    dialog = SongDialog(["经典喊麦"], "经典喊麦", has_stems=True, plan=plan)
    try:
        assert dialog.height() <= dialog.sizeHint().height() + 2
        assert dialog.height() >= dialog.minimumSizeHint().height()
        assert dialog.height() < 560  # No fixed tall dialog with empty space below the form.
        assert dialog.width() >= 420
    finally:
        dialog.reject()
        dialog.deleteLater()


def test_preview_close_stops_playback_and_export_fields_have_labels(appearance):
    appearance.set_mode("dark")
    audio = np.zeros((64, 1), dtype=np.float32)
    preview = PreviewDialog((audio, audio), (-20, -18), 44100, None, 0.5, None)
    export = ExportDialog(1, {"lufs": -15, "true_peak_db": -1}, None)
    try:
        stop = Mock()
        preview.player.stop = stop
        close = preview.findChild(QDialogButtonBox).button(QDialogButtonBox.Close)
        assert close.isEnabled()
        preview.show()
        close.click()
        assert preview.result() == QDialog.Rejected and not preview.isVisible()
        stop.assert_called_once()
        assert all(_has_label(control, export) for control in (
            export.format, export.rate, export.bits, export.channels,
        ))
        assert export.value() == ("wav", 44100, 24, 2)
    finally:
        preview.deleteLater()
        export.deleteLater()
