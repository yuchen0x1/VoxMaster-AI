"""Semantic Qt colors, control states and live system/light/dark appearance."""
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from .platforms import ui_font

MODES = ("system", "light", "dark")
SPACING = (4, 8, 12, 16, 24, 32)
RADII = {"control": 6, "card": 8}
FONT_SIZES = {"body": 10, "caption": 9, "section": 11, "title": 18}
MOTION = {"duration_ms": 0}  # Instant changes respect reduced-motion preferences.
COLORS = {
    "light": {
        "window": "#F4F5FA", "surface": "#FFFFFF", "panel": "#EEF0F7",
        "input": "#FFFFFF", "elevated": "#FFFFFF", "text": "#222334",
        "muted": "#55586D", "disabled": "#707486", "disabled_bg": "#EBEDF3",
        "border": "#6E7387", "divider": "#CCD0DD", "hover": "#E8E4F7",
        "pressed": "#DACEF4", "accent": "#6845C4", "accent_hover": "#5937B1",
        "on_accent": "#FFFFFF", "selected": "#E6DDF9", "on_selected": "#3E2575",
        "focus": "#663DC2", "success": "#23734C", "warning": "#8A5100",
        "error": "#B52D39", "info": "#216896", "canvas": "#FCFCFF",
        "grid": "#E0E3EC", "grid_strong": "#737B90", "wave_a": "#6749BE",
        "wave_b": "#146D8E", "cursor": "#2C1A52", "track_vocal": "#6749BE",
        "track_music": "#146D8E", "track_fx": "#23734C", "band_low": "#9C5600",
        "band_mid": "#6845C4", "band_high": "#146D8E",
    },
    "dark": {
        "window": "#15151D", "surface": "#1D1D28", "panel": "#20202D",
        "input": "#282835", "elevated": "#2C2C3B", "text": "#F1F0F7",
        "muted": "#B9B8CB", "disabled": "#9D9BAE", "disabled_bg": "#242430",
        "border": "#8C8EA5", "divider": "#414151", "hover": "#383348",
        "pressed": "#443759", "accent": "#B69AFF", "accent_hover": "#C8B2FF",
        "on_accent": "#20142F", "selected": "#47385F", "on_selected": "#F0E5FF",
        "focus": "#C5A8FF", "success": "#82CCA3", "warning": "#F0BC73",
        "error": "#FF9CA7", "info": "#8ECFF0", "canvas": "#14141E",
        "grid": "#303040", "grid_strong": "#85879D", "wave_a": "#B69AFF",
        "wave_b": "#83D0EB", "cursor": "#F4EBFF", "track_vocal": "#B69AFF",
        "track_music": "#83D0EB", "track_fx": "#82CCA3", "band_low": "#F0BC73",
        "band_mid": "#B69AFF", "band_high": "#83D0EB",
    },
}


def normalize_mode(mode):
    return mode if isinstance(mode, str) and mode in MODES else "system"


def stylesheet(scheme="dark"):
    c = COLORS[scheme]
    # Keep the native font fallback and metric-sized controls; no raster icons.
    return f'''
QWidget {{color:{c['text']};font-family:"{ui_font()}";font-size:{FONT_SIZES['body']}pt;
    selection-background-color:{c['accent']};selection-color:{c['on_accent']};}}
QMainWindow,QDialog {{background:{c['window']};}}
QFrame#side,QFrame#inspector {{background:{c['panel']};}}
QWidget#inspectorContent,QWidget#sideContent {{background:{c['panel']};}}
QScrollArea#inspectorScroll {{background:transparent;}}
QLabel {{background:transparent;}}
QLabel#brand {{font-size:20px;font-weight:700;}}
QLabel#title {{font-size:{FONT_SIZES['title']}pt;font-weight:600;}}
QLabel#section {{font-size:{FONT_SIZES['section']}pt;font-weight:600;}}
QLabel#sub {{color:{c['muted']};font-size:{FONT_SIZES['caption']}pt;}}
QLabel#value {{font-family:Consolas,monospace;color:{c['accent']};font-size:18px;}}
QLabel#clock {{font-family:Consolas,monospace;font-size:21px;color:{c['text']};}}
QLabel[status="success"],QLabel#sub[status="success"] {{color:{c['success']};}}
QLabel[status="warning"],QLabel#sub[status="warning"] {{color:{c['warning']};}}
QLabel[status="error"],QLabel#sub[status="error"] {{color:{c['error']};}}
QLabel[status="info"],QLabel#sub[status="info"] {{color:{c['info']};}}
QPushButton,QToolButton,QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit,QPlainTextEdit,QTextEdit {{
    background:{c['input']};color:{c['text']};border:1px solid {c['border']};
    border-radius:{RADII['control']}px;padding:6px 8px;}}
QPushButton,QToolButton,QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit {{min-height:20px;}}
QPushButton:hover,QToolButton:hover,QComboBox:hover {{background:{c['hover']};}}
QPushButton:pressed,QToolButton:pressed {{background:{c['pressed']};}}
QPushButton:checked,QToolButton:checked {{background:{c['selected']};color:{c['on_selected']};}}
QPushButton:checked:hover,QToolButton:checked:hover {{background:{c['pressed']};}}
QPushButton:focus,QToolButton:focus,QComboBox:focus,QLineEdit:focus,QPlainTextEdit:focus,
QTextEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,QListWidget:focus,QTreeWidget:focus,
QTableWidget:focus {{border:2px solid {c['focus']};padding:5px 7px;}}
QPushButton:disabled,QToolButton:disabled,QComboBox:disabled,QSpinBox:disabled,
QDoubleSpinBox:disabled,QLineEdit:disabled,QPlainTextEdit:disabled,QTextEdit:disabled {{
    color:{c['disabled']};background:{c['disabled_bg']};}}
QPushButton#primary,QPushButton#songApply {{background:{c['accent']};color:{c['on_accent']};font-weight:700;
    padding:8px 16px;border:1px solid {c['accent']};}}
QPushButton#primary:hover,QPushButton#songApply:hover {{background:{c['accent_hover']};border-color:{c['accent_hover']};}}
QPushButton#primary:pressed,QPushButton#songApply:pressed {{background:{c['accent']};border-color:{c['text']};}}
QPushButton#primary:focus,QPushButton#songApply:focus {{border:2px solid {c['text']};padding:7px 15px;}}
QPushButton#primary:disabled,QPushButton#songApply:disabled {{background:{c['disabled_bg']};color:{c['disabled']};border-color:{c['border']};}}
QPushButton#nav {{text-align:left;background:transparent;padding:8px 10px;color:{c['muted']};border:1px solid transparent;}}
QPushButton#nav:hover,QPushButton#nav:checked {{background:{c['selected']};color:{c['on_selected']};}}
QPushButton#nav:pressed {{background:{c['pressed']};}}
QPushButton#nav:focus {{border:2px solid {c['focus']};padding:7px 9px;}}
QFrame#rule {{background:{c['divider']};color:{c['divider']};max-height:1px;min-height:1px;}}
QScrollArea {{border:0;background:transparent;}}
QScrollArea>QWidget>QWidget {{background:transparent;}}
QGroupBox {{border:1px solid {c['divider']};border-radius:{RADII['card']}px;
    margin-top:{SPACING[2]}px;padding-top:{SPACING[2]}px;}}
QGroupBox::title {{subcontrol-origin:margin;left:8px;padding:0 4px;}}
QTabWidget::pane {{background:{c['surface']};border:1px solid {c['border']};border-radius:6px;}}
QTabBar::tab {{background:{c['panel']};border:1px solid {c['border']};padding:8px 12px;}}
QTabBar::tab:selected {{background:{c['selected']};color:{c['on_selected']};border-bottom:3px solid {c['accent']};}}
QTabBar::tab:hover {{background:{c['hover']};}}
QTabBar::tab:focus {{border:2px solid {c['focus']};}}
QTabBar::tab:disabled {{color:{c['disabled']};}}
QTabBar::scroller {{width:22px;}}
QTabBar QToolButton {{background:{c['panel']};border:1px solid {c['border']};padding:0;
    margin:0;min-height:18px;min-width:18px;}}
QTabBar QToolButton:hover {{background:{c['hover']};}}
QSlider::groove:horizontal {{height:4px;background:{c['border']};border-radius:2px;}}
QSlider::sub-page:horizontal {{background:{c['accent']};border-radius:2px;}}
QSlider::handle:horizontal {{background:{c['accent']};border:1px solid {c['border']};width:14px;
    margin:-6px 0;border-radius:7px;}}
QSlider::handle:horizontal:hover {{background:{c['accent_hover']};}}
QSlider::handle:horizontal:focus {{border:2px solid {c['focus']};}}
QSlider::handle:horizontal:disabled {{background:{c['disabled']};}}
QProgressBar {{border:1px solid {c['border']};border-radius:3px;background:{c['input']};
    color:{c['text']};text-align:center;min-height:4px;}}
QProgressBar::chunk {{background:{c['accent']};border-radius:2px;}}
QToolTip {{background:{c['elevated']};color:{c['text']};border:1px solid {c['border']};padding:6px;}}
QMenu,QMenuBar {{background:{c['elevated']};color:{c['text']};}}
QMenu {{border:1px solid {c['border']};padding:4px;}}
QMenu::item {{padding:7px 24px 7px 12px;}}
QMenu::item:selected,QMenuBar::item:selected {{background:{c['selected']};color:{c['on_selected']};}}
QMenu::item:disabled {{color:{c['disabled']};}}
QMenu::separator {{height:1px;background:{c['divider']};margin:4px;}}
QComboBox QAbstractItemView {{background:{c['elevated']};color:{c['text']};border:1px solid {c['border']};
    selection-background-color:{c['accent']};selection-color:{c['on_accent']};}}
QTableView,QTableWidget,QTreeWidget,QListWidget,QAbstractItemView {{
    background:{c['surface']};alternate-background-color:{c['panel']};
    color:{c['text']};border:1px solid {c['border']};border-radius:6px;padding:4px;}}
QAbstractItemView::item {{min-height:24px;padding:2px;}}
QAbstractItemView::item:hover {{background:{c['hover']};}}
QAbstractItemView::item:selected {{background:{c['accent']};color:{c['on_accent']};}}
QAbstractItemView::item:focus {{border:1px solid {c['focus']};}}
QHeaderView::section {{background:{c['panel']};color:{c['text']};padding:6px;border:0;
    border-bottom:1px solid {c['border']};border-right:1px solid {c['divider']};}}
QTableCornerButton::section {{background:{c['panel']};border:1px solid {c['border']};}}
QScrollBar:vertical {{background:{c['panel']};width:12px;margin:0;}}
QScrollBar:horizontal {{background:{c['panel']};height:12px;margin:0;}}
QScrollBar::handle {{background:{c['border']};border:2px solid {c['panel']};border-radius:5px;}}
QScrollBar::handle:vertical {{min-height:28px;}}
QScrollBar::handle:horizontal {{min-width:28px;}}
QScrollBar::handle:hover {{background:{c['accent']};}}
QScrollBar::add-line,QScrollBar::sub-line {{width:0;height:0;}}
QScrollBar::add-page,QScrollBar::sub-page {{background:transparent;}}
QSplitter::handle {{background:{c['divider']};}}
QSplitter::handle:hover {{background:{c['accent']};}}
QCheckBox,QRadioButton {{spacing:7px;min-height:24px;
    border:2px solid transparent;border-radius:3px;}}
QCheckBox:focus,QRadioButton:focus {{border-color:{c['focus']};}}
QCheckBox:disabled,QRadioButton:disabled {{color:{c['disabled']};}}
QCheckBox::indicator,QRadioButton::indicator {{width:16px;height:16px;}}
'''


def palette(scheme):
    c = COLORS[scheme]
    result = QPalette()
    roles = {
        "Window": "window", "WindowText": "text", "Base": "input",
        "AlternateBase": "panel", "ToolTipBase": "elevated", "ToolTipText": "text",
        "Text": "text", "Button": "input", "ButtonText": "text",
        "BrightText": "on_accent", "Highlight": "accent", "HighlightedText": "on_accent",
        "Link": "accent", "LinkVisited": "accent", "PlaceholderText": "muted",
        "Light": "border", "Midlight": "panel", "Mid": "border", "Dark": "divider",
        "Shadow": "divider", "Accent": "accent",
    }
    for role, token in roles.items():
        qt_role = getattr(QPalette.ColorRole, role, None)
        if qt_role is not None:
            result.setColor(qt_role, QColor(c[token]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.PlaceholderText):
        result.setColor(QPalette.Disabled, role, QColor(c["disabled"]))
    result.setColor(QPalette.Disabled, QPalette.Base, QColor(c["disabled_bg"]))
    result.setColor(QPalette.Disabled, QPalette.Button, QColor(c["disabled_bg"]))
    return result


class ThemeManager(QObject):
    changed = Signal(str)

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.mode = "system"
        self.resolved = "dark"
        self._installed = False
        hints = app.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._system_changed)

    def _system_scheme(self):
        return "dark" if self.app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"

    def set_mode(self, mode):
        self.mode = normalize_mode(mode)
        scheme = self._system_scheme() if self.mode == "system" else self.mode
        if self._installed and scheme == self.resolved:
            return
        self.resolved = scheme
        self._installed = True
        self.app.setPalette(palette(scheme))
        self.app.setStyleSheet(stylesheet(scheme))
        self.changed.emit(scheme)
        for widget in self.app.topLevelWidgets():
            QWidget.update(widget)

    def _system_changed(self, _scheme):
        if self.mode == "system":
            self.set_mode("system")


def manager(app=None):
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("Theme manager requires QApplication")
    current = getattr(app, "_vox_theme_manager", None)
    if current is None:
        current = ThemeManager(app)
        app._vox_theme_manager = current
    return current


def install_theme(app, mode="system"):
    current = manager(app)
    current.set_mode(mode)
    return current


def color(token):
    app = QApplication.instance()
    scheme = manager(app).resolved if app is not None else "dark"
    return QColor(COLORS[scheme][token])


def watch_theme(widget, callback=None):
    manager().changed.connect(callback if callback is not None else widget.update)


def set_status(widget, status):
    """Repolish a semantic state without retaining a stale inline color."""
    widget.setProperty("status", status)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
