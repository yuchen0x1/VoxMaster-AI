import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QWidget

from vox.studio import StudioDialog
from vox.studio_mix_dialogs import BalanceDialog, RackDialog
from vox.studio_session import Session
from vox.studio_timeline import COLORS, Timeline
from vox.theme import color, manager


SR = 8000


def sources(seconds=2):
    silence = np.zeros((SR * seconds, 2), dtype=np.float32)
    return {"Vocal": silence, "Instrumental": silence.copy()}


def test_timeline_keyboard_navigation_and_existing_signals(qt_session_app):
    wave = Timeline(Session(sources(), SR))
    wave.resize(640, 260)
    wave.show()
    wave.setFocus()
    qt_session_app.processEvents()

    seek_positions = []
    selections = []
    wave.seek_requested.connect(lambda: seek_positions.append(wave.cursor))
    wave.selection_changed.connect(lambda: selections.append((wave.first, wave.last)))

    QTest.keyClick(wave, Qt.Key_Right)
    assert wave.cursor == round(SR * 0.1)
    QTest.keyClick(wave, Qt.Key_Right, Qt.ShiftModifier)
    assert wave.cursor == round(SR * 0.1) + SR
    QTest.keyClick(wave, Qt.Key_Left)
    assert wave.cursor == round(SR * 0.1) + SR - round(SR * 0.1)
    QTest.keyClick(wave, Qt.Key_Home)
    assert wave.cursor == 0
    QTest.keyClick(wave, Qt.Key_End)
    assert wave.cursor == wave.total

    assert seek_positions == [
        0,
        round(SR * 0.1),
        round(SR * 0.1) + SR,
        round(SR * 0.1) + SR - round(SR * 0.1),
        0,
    ]
    assert selections[-2:] == [(0, 0), (wave.total, wave.total)]
    assert wave.accessibleName() == "多轨时间轴"
    assert "Shift" in wave.accessibleDescription()
    assert wave.hasFocus()
    wave.close()


def test_zoomed_keyboard_cursor_stays_visible_and_updates_scrollbar(qt_session_app):
    dialog = StudioDialog(sources(10), SR)
    try:
        dialog.show()
        qt_session_app.processEvents()
        wave = dialog.wave
        wave.change_zoom(8)
        wave.setFocus()
        for key in (Qt.Key_End, Qt.Key_Home, Qt.Key_Right, Qt.Key_End, Qt.Key_Left):
            QTest.keyClick(wave, key)
            qt_session_app.processEvents()
            assert wave.offset <= wave.cursor <= wave.offset + wave.span
            assert wave.left <= wave.x_for(wave.cursor) <= wave.width()
            expected = round(wave.offset / max(1, wave.total - wave.span)
                             * dialog.scroll.maximum())
            assert dialog.scroll.value() == expected
        assert wave.cursor == wave.total - round(SR * 0.1)
    finally:
        dialog.reject()


def test_space_operates_focused_checkbox_before_transport(qt_session_app, monkeypatch):
    played = []
    monkeypatch.setattr(StudioDialog, "_play", lambda self: played.append(True))
    dialog = StudioDialog(sources(), SR)
    try:
        dialog.show()
        dialog.loop.setFocus()
        qt_session_app.processEvents()
        QTest.keyClick(dialog.loop, Qt.Key_Space)
        assert dialog.loop.isChecked()
        assert played == []
        dialog.play_button.setFocus()
        qt_session_app.processEvents()
        QTest.keyClick(dialog.play_button, Qt.Key_Space)
        assert played == [True]
        dialog.wave.setFocus()
        qt_session_app.processEvents()
        QTest.keyClick(dialog.wave, Qt.Key_Space)
        assert played == [True, True]
    finally:
        dialog.reject()


def test_timeline_repaints_with_semantic_light_and_dark_tokens(qt_session_app):
    theme = manager(qt_session_app)
    previous_mode = theme.mode
    wave = Timeline(Session(sources(), SR))
    wave.setFocusPolicy(Qt.NoFocus)
    wave.resize(640, 260)
    wave.show()

    try:
        theme.set_mode("dark")
        qt_session_app.processEvents()
        dark_pixel = (
            wave.grab().toImage().pixelColor(wave.width() - 4, wave.height() - 4)
        )
        assert dark_pixel == color("canvas")
        theme.set_mode("light")
        qt_session_app.processEvents()
        light_pixel = (
            wave.grab().toImage().pixelColor(wave.width() - 4, wave.height() - 4)
        )
        assert light_pixel == color("canvas")
        assert dark_pixel != light_pixel
    finally:
        theme.set_mode(previous_mode)
        wave.close()

    # Public legacy colors remain available for callers using the old API.
    assert set(COLORS) == {"Vocal", "Instrumental", "FX", "Master"}


def test_studio_layout_uses_global_theme_and_keeps_accessible_controls(qt_session_app):
    dialog = StudioDialog(sources(), SR)
    try:
        dialog.resize(560, 420)
        dialog.show()
        qt_session_app.processEvents()

        assert dialog.minimumSize().width() == 560
        assert dialog.minimumSize().height() == 420
        assert dialog.status.wordWrap()
        assert dialog.headroom.wordWrap()
        assert dialog.master.accessibleName() == "主总线电平"
        master_label = next(
            label for label in dialog.findChildren(QLabel) if label.text() == "主总线"
        )
        assert master_label.buddy() is dialog.master
        assert dialog.scroll.accessibleName() == "时间轴水平滚动条"
        assert dialog.wave.accessibleDescription()
        assert dialog.wave.focusPolicy() == Qt.StrongFocus

        buttons = dialog.findChildren(QPushButton)
        names = {button.accessibleName() for button in buttons}
        assert {"缩小时间轴", "放大时间轴"} <= names
        assert all(
            not button.isHidden()
            for button in buttons
            if button is not dialog.cancel_button
        )
        workspace = next(
            area
            for area in dialog.findChildren(QScrollArea)
            if area.accessibleName() == "多轨混音工作区"
        )
        assert workspace.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
        assert workspace.horizontalScrollBar().maximum() > 0
        assert workspace.verticalScrollBar().maximum() > 0
        assert all(not widget.styleSheet() for widget in dialog.findChildren(QWidget))
        assert not dialog.styleSheet()
    finally:
        dialog.reject()


def test_mix_dialogs_have_scrollable_accessible_forms_and_buddies(qt_session_app):
    session = Session(sources(), SR)
    reading = {"lufs": -20.0, "correlation": 0.8, "mono_db": -1.0, "peak_db": -6.0}
    report = {
        "tracks": {name: dict(reading) for name in ("Vocal", "Instrumental", "Master")},
        "recommendation": None,
    }
    rack = RackDialog(session, "Vocal", None)
    balance = BalanceDialog(session, report, None)
    try:
        for dialog in (rack, balance):
            assert dialog.accessibleName()
            assert dialog.minimumSize().width() > 0
            assert dialog.findChildren(QScrollArea)
            dialog.show()
        qt_session_app.processEvents()

        assert rack.target.accessibleName() == "效果器目标轨道"
        target_label = next(
            label for label in rack.findChildren(QLabel) if label.text() == "处理轨道"
        )
        assert target_label.buddy() is rack.target
        for widget in rack.values.values():
            assert widget.accessibleName()

        assert balance.gain.accessibleName() == "伴奏电平"
        assert (
            balance.balance_page.layout().labelForField(balance.gain).buddy()
            is balance.gain
        )
        assert balance.match_track.accessibleName() == "响度匹配目标轨道"
        assert balance.target.accessibleName() == "目标综合响度"
        for widget in balance.routing.values():
            assert widget.accessibleName()
    finally:
        rack.close()
        balance.close()
