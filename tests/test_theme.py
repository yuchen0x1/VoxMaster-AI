from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QCheckBox, QDialog, QRadioButton, QStyle, QStyleOptionButton

from vox.settings_dialog import SettingsDialog
from vox.theme import COLORS, manager, palette, stylesheet


def _luminance(hex_color):
    values = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in values
    ]
    return sum(weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), linear))


def _contrast(first, second):
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_theme_text_focus_and_selected_states_meet_contrast(qt_session_app):
    pairs = (
        ("text", "surface"),
        ("muted", "window"),
        ("on_selected", "selected"),
        ("on_accent", "accent"),
        ("focus", "window"),
    )
    for scheme in ("light", "dark"):
        for foreground, background in pairs:
            assert _contrast(COLORS[scheme][foreground], COLORS[scheme][background]) >= 4.5
        for background in ("window", "input", "hover", "pressed", "selected"):
            assert _contrast(COLORS[scheme]["border"], COLORS[scheme][background]) >= 3.0
        for token in ("muted", "wave_a", "wave_b", "band_low", "band_mid", "band_high", "cursor"):
            assert _contrast(COLORS[scheme][token], COLORS[scheme]["canvas"]) >= 4.5
        colors = palette(scheme)
        expected = COLORS[scheme]["window"]
        assert colors.color(QPalette.Window).name().lower() == expected.lower()
        qss = stylesheet(scheme)
        assert "QTableView" in qss
        assert "QHeaderView::section" in qss
        assert "QMenu::item:selected" in qss
        assert "QPushButton#primary:focus" in qss


def test_settings_preview_applies_and_cancel_restores(qt_session_app):
    theme = manager(qt_session_app)
    previous = theme.mode
    theme.set_mode("dark")
    dialog = SettingsDialog({}, {})
    dialog.theme_choice.setCurrentIndex(dialog.theme_choice.findData("light"))
    qt_session_app.processEvents()

    assert theme.mode == "light"
    assert theme.resolved == "light"
    dialog.reject()
    qt_session_app.processEvents()
    assert theme.mode == "dark"
    assert dialog.result() == QDialog.Rejected
    dialog.close()
    theme.set_mode(previous)


def test_settings_value_persists_theme_without_changing_old_settings(qt_session_app):
    theme = manager(qt_session_app)
    previous = theme.mode
    settings = {"custom_key": "retained"}
    dialog = SettingsDialog(settings, {})
    dialog.theme_choice.setCurrentIndex(dialog.theme_choice.findData("dark"))
    values = dialog.value()
    assert values["theme"] == "dark"
    assert values["custom_key"] == "retained"
    assert "theme" not in settings
    dialog.reject()
    theme.set_mode(previous)


def test_native_choice_indicators_have_visible_shapes_in_both_themes(qt_session_app):
    theme = manager(qt_session_app)
    previous = theme.mode
    checkbox, radio = QCheckBox(), QRadioButton()
    radio.setAutoExclusive(False)
    try:
        for mode in ("light", "dark"):
            theme.set_mode(mode)
            for widget, element in ((checkbox, QStyle.SE_CheckBoxIndicator),
                                    (radio, QStyle.SE_RadioButtonIndicator)):
                widget.resize(100, 40)
                widget.show()
                states = []
                for checked in (False, True):
                    widget.setChecked(checked)
                    qt_session_app.processEvents()
                    option = QStyleOptionButton()
                    widget.initStyleOption(option)
                    rect = widget.style().subElementRect(element, option, widget)
                    pixmap = widget.grab()
                    scale = pixmap.devicePixelRatio()
                    image = pixmap.toImage()
                    pixels = tuple(image.pixelColor(x, y).rgba()
                                   for y in range(round(rect.top() * scale),
                                                  round((rect.bottom() + 1) * scale))
                                   for x in range(round(rect.left() * scale),
                                                  round((rect.right() + 1) * scale)))
                    assert len(set(pixels)) > 1, (mode, type(widget).__name__, checked)
                    states.append(pixels)
                assert states[0] != states[1]  # Native check mark / radio dot, not only text.
    finally:
        checkbox.close()
        radio.close()
        theme.set_mode(previous)


def test_model_center_button_does_not_shadow_theme_refresh(qt_session_app):
    from vox.models import ModelDialog
    theme = manager(qt_session_app)
    previous = theme.mode
    dialog = ModelDialog()
    try:
        dialog.show()
        assert not callable(dialog.update)  # Retain its existing public button API.
        for mode in ("dark", "light", "dark"):
            theme.set_mode(mode)
            qt_session_app.processEvents()
            assert dialog.palette().color(QPalette.Window).name() == COLORS[mode]["window"].lower()
    finally:
        dialog.close()
        dialog.deleteLater()
        qt_session_app.processEvents()
        theme.set_mode(previous)


def test_system_mode_tracks_qt_color_scheme(qt_session_app):
    theme = manager(qt_session_app)
    previous = theme.mode
    theme.set_mode("system")
    expected = theme._system_scheme()
    assert expected in ("light", "dark")
    assert theme.resolved == expected
    theme._system_changed(None)
    assert theme.resolved == expected
    theme.set_mode(previous)
