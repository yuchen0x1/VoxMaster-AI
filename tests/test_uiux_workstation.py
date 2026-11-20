import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QScrollArea

from vox.visual import ElidedLabel, Spectrum, Timeline, envelope
from vox.theme import color, manager


def test_workstation_keyboard_seek_selection_and_import(qt_session_app):
    wave = Timeline()
    seeks, selections, imports = [], [], []
    wave.seek.connect(seeks.append)
    wave.selected.connect(lambda a, b: selections.append((a, b)))
    wave.import_requested.connect(lambda: imports.append(True))
    wave.show()
    QTest.keyClick(wave, Qt.Key_Return)
    assert imports == [True]
    data = np.zeros((80, 2), dtype=np.float32)
    wave.set_data(envelope(data), None, 2.0)
    QTest.keyClick(wave, Qt.Key_Right)
    assert seeks == [0.1]
    QTest.keyClick(wave, Qt.Key_Right, Qt.ShiftModifier)
    assert selections[-1] == (0.1, 0.2)
    QTest.keyClick(wave, Qt.Key_End)
    assert seeks[-1] == 2.0
    QTest.keyClick(wave, Qt.Key_Home)
    assert seeks[-1] == 0.0
    assert wave.focusPolicy() == Qt.StrongFocus
    assert wave.accessibleName()
    wave.close()


def test_workstation_shift_selection_extends_with_real_seek_handler(qt_session_app, monkeypatch):
    from vox.interface import MainWindow
    monkeypatch.setattr(MainWindow, "detect", lambda self: None)
    window = MainWindow()
    audio = np.zeros((44100 * 3, 2), dtype=np.float32)
    monkeypatch.setattr(window, "audio", lambda: audio)
    window.timeline.set_data(envelope(audio), None, 3.0)
    try:
        QTest.keyClick(window.timeline, Qt.Key_Right)
        for _ in range(3):
            QTest.keyClick(window.timeline, Qt.Key_Right, Qt.ShiftModifier)
        assert window.timeline.region == pytest.approx((0.1, 0.4))
        assert window.cursor == pytest.approx(0.1)
    finally:
        window.close()


def test_space_keeps_native_control_action_and_plays_from_canvas(qt_session_app, monkeypatch):
    from vox.interface import MainWindow
    monkeypatch.setattr(MainWindow, "detect", lambda self: None)
    monkeypatch.setattr(MainWindow, "play", lambda self: setattr(self, "_played", True))
    window = MainWindow()
    try:
        window.show()
        window.loop.setFocus()
        qt_session_app.processEvents()
        QTest.keyClick(window.loop, Qt.Key_Space)
        assert window.loop.isChecked()
        assert not getattr(window, "_played", False)
        window.loop.click()
        window.timeline.setFocus()
        qt_session_app.processEvents()
        QTest.keyClick(window.timeline, Qt.Key_Space)
        assert getattr(window, "_played", False)
    finally:
        window.close()


def test_settings_failure_rolls_back_device_cache_and_theme(qt_session_app, monkeypatch, tmp_path):
    from vox import audioio
    from vox.interface import MainWindow
    from vox.settings_dialog import SettingsDialog

    monkeypatch.setattr(MainWindow, "detect", lambda self: None)
    previous_cache = audioio.cache_directory()
    window = MainWindow()
    window.device_report = {
        "devices": [dict(id=i, name=f"输出{i}", host="Test", outputs=2, inputs=0)
                    for i in (1, 2)],
        "default_output": 1,
    }
    window.player.device = 1
    old_cache, new_cache = tmp_path / "old-cache", tmp_path / "new-cache"
    old_settings = {"theme": "dark", "output_device": 1, "cache_dir": str(old_cache)}
    window.settings = old_settings
    audioio.set_cache_directory(old_cache)
    theme = manager()
    previous_mode = theme.mode
    theme.set_mode("dark")
    errors = []

    def accepted(dialog):
        dialog.output.setCurrentIndex(dialog.output.findData(2))
        dialog.theme_choice.setCurrentIndex(dialog.theme_choice.findData("light"))
        dialog._paths["cache_dir"].setText(str(new_cache))
        dialog.accept()
        assert theme.mode == "light"
        return dialog.result()

    def denied():
        raise PermissionError("denied")

    monkeypatch.setattr(SettingsDialog, "exec", accepted)
    monkeypatch.setattr(window, "save_settings", denied)
    monkeypatch.setattr(window, "failed", errors.append)
    try:
        window.settings_view()
        assert errors == ["denied"]
        assert window.player.device == 1
        assert window.settings is old_settings
        assert audioio.cache_directory() == old_cache.resolve()
        assert theme.mode == "dark"
        assert "输出1" in window.device_button.text()
    finally:
        audioio.set_cache_directory(previous_cache)
        theme.set_mode(previous_mode)
        window.close()


def test_workstation_canvases_repaint_without_recreation(qt_session_app):
    theme = manager()
    before = theme.mode
    wave, spectrum = Timeline(), Spectrum()
    for widget in (wave, spectrum):
        widget.resize(500, 200)
        widget.setFocusPolicy(Qt.NoFocus)
        widget.show()
    try:
        images = []
        for scheme in ("dark", "light", "dark"):
            theme.set_mode(scheme)
            qt_session_app.processEvents()
            colors = []
            for widget in (wave, spectrum):
                image = widget.grab().toImage()
                point = image.pixelColor(image.width() - 2, 2)
                assert point == color("canvas")
                colors.append(point.name())
            images.append(colors)
        assert images[0] != images[1]
        assert images[0] == images[2]
    finally:
        theme.set_mode(before)
        wave.close()
        spectrum.close()


def test_long_title_preserves_full_text_for_accessibility(qt_session_app):
    name = "中文长工程名称_" * 25 + "Mandarin.wav"
    label = ElidedLabel(name, "title")
    label.setText(name)
    label.resize(120, 30)
    label.show()
    qt_session_app.processEvents()
    assert label.text() == name
    assert label.toolTip() == name
    assert label.accessibleDescription() == name
    assert not label.grab().isNull()
    label.close()


def test_inspector_wrapped_reports_keep_full_height_in_small_window(qt_session_app, monkeypatch):
    from vox.interface import MainWindow
    monkeypatch.setattr(MainWindow, "detect", lambda self: None)
    window = MainWindow()
    window.resize(820, 560)
    try:
        window.show()
        report = ("综合响度 -42.2 LUFS，4 倍过采样真峰值 -23.6 dBTP。\n\n"
                  "220–550 Hz 占分析频带能量的 49%，可尝试削减浑浊感。\n\n"
                  "活动帧电平的 10–90 百分位相差 20.8 dB，建议适量压缩。\n\n"
                  "检测到 3 个持续发声后进入停顿的位置，可编辑尾音发送。")
        for widget in (window.issues, window.plan_label, window.match_label):
            widget.setText(report)
        for _ in range(3):
            qt_session_app.processEvents()
        for widget in (window.issues, window.plan_label, window.match_label):
            assert widget.height() >= widget.heightForWidth(widget.width())
            assert widget.minimumHeight() >= widget.heightForWidth(widget.width())
            assert widget.height() > widget.fontMetrics().height() * 4
        assert window.full.geometry().top() > window.issues.geometry().bottom()
        assert window.advanced.geometry().bottom() < window.plan_label.geometry().top()
        assert window.plan_label.geometry().bottom() < window.match_label.geometry().top()
        area = next(area for area in window.findChildren(QScrollArea)
                    if area.objectName() == "inspectorScroll")
        assert area.verticalScrollBar().maximum() > 0
        area.ensureWidgetVisible(window.match_label)
        qt_session_app.processEvents()
        assert area.verticalScrollBar().value() > 0
    finally:
        window.close()


@pytest.mark.parametrize("size", [(820, 560), (920, 620), (1280, 790)])
def test_workstation_small_window_keeps_scrollable_navigation(qt_session_app, monkeypatch, size):
    from vox.interface import MainWindow
    monkeypatch.setattr(MainWindow, "detect", lambda self: None)
    window = MainWindow()
    window.resize(*size)
    window.show()
    qt_session_app.processEvents()
    try:
        assert window.size().width() <= size[0]
        assert window.size().height() <= size[1]
        areas = window.findChildren(QScrollArea)
        assert {"工作站导航", "工作台内容"} <= {area.accessibleName() for area in areas}
        assert window.project_name.width() >= 48
        assert window.project_name.isVisibleTo(window)
        assert window.timeline.accessibleName() == "音频时间轴"
        assert window.stop_btn.accessibleName()
        assert window.style.accessibleName()
        assert window.kind.accessibleName()
        assert window.device_button.isVisibleTo(window)
        assert window.go.isVisibleTo(window)
    finally:
        window.close()
