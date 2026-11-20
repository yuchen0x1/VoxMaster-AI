"""Qt painting for the timeline and transport meters."""

import numpy as np
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QObject, QEvent
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QIcon
from PySide6.QtWidgets import (
    QApplication, QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox,
    QLineEdit, QPlainTextEdit, QTextEdit, QWidget, QLabel, QSizePolicy,
)

from .theme import color as theme_color, stylesheet, watch_theme

# Compatibility for older launchers; the application uses install_theme().
STYLES = stylesheet("dark")


def app_icon():
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#a989ff"))  # Fixed brand artwork, not a UI surface.
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    p.setPen(QPen(QColor("#20132c"), 4, Qt.SolidLine, Qt.RoundCap))
    for i, height in enumerate([10, 22, 36, 24, 14]):
        x = 14 + i * 9
        p.drawLine(x, 32 - height // 2, x, 32 + height // 2)
    p.end()
    return QIcon(pix)


class TransportShortcutGuard(QObject):
    """Leave Space to focused controls; retain transport playback on the canvas."""
    def __init__(self, window, shortcut):
        super().__init__(window)
        self.shortcut = shortcut
        QApplication.instance().focusChanged.connect(self._focus_changed)
        self._focus_changed(None, QApplication.focusWidget())

    def _focus_changed(self, old, focus):
        controls = (QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox,
                    QLineEdit, QPlainTextEdit, QTextEdit)
        self.shortcut.setEnabled(not isinstance(focus, controls))


class WrappedLabel(QLabel):
    """Keep paragraphs complete inside a resizable, vertically scrolling panel."""
    def __init__(self, text, role="", parent=None):
        super().__init__(text, parent)
        self.setObjectName(role)
        self.setTextFormat(Qt.PlainText)
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self._fit_height()

    def _fit_height(self):
        height = max(0, self.heightForWidth(max(1, self.width())))
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)

    def setText(self, text):
        super().setText(text)
        self._fit_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._fit_height()


class ElidedLabel(QLabel):
    """Keep the complete name accessible while fitting long project/track names."""
    def __init__(self, text, role="", parent=None):
        super().__init__(text, parent)
        self.setObjectName(role)
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.setToolTip(text)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)
        self.setAccessibleDescription(text)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(self.palette().windowText().color())
        p.drawText(self.contentsRect(), self.alignment(), self.fontMetrics().elidedText(
            self.text(), Qt.ElideMiddle, self.contentsRect().width()))
        p.end()


def timecode(seconds):
    seconds = max(0, float(seconds))
    return f"{int(seconds) // 60:02}:{int(seconds) % 60:02}.{int(seconds * 100) % 100:02}"


def envelope(audio, count=3000):
    if audio is None or not len(audio):
        return None
    step = max(1, (len(audio) + count - 1) // count)
    starts = np.arange(0, len(audio), step)
    return np.stack(
        (
            np.minimum.reduceat(audio.min(axis=1), starts),
            np.maximum.reduceat(audio.max(axis=1), starts),
        ),
        axis=1,
    )


class Timeline(QWidget):
    seek = Signal(float)
    selected = Signal(float, float)
    import_requested = Signal()

    def __init__(self):
        super().__init__()
        self.peaks = [None, None]
        self.lengths = [0.0, 0.0]
        self.duration = 0.0
        self.cursor = 0.0
        self.region = None
        self.anchor = None
        self._key_anchor = None
        self._key_position = None
        self.setMinimumHeight(168)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("音频时间轴")
        self.setAccessibleDescription(
            "左右方向键定位，Ctrl 加方向键每次一秒，Shift 加方向键选择区间，Home 或 End 跳到首尾；空轨按 Enter 导入。")
        self.setToolTip("单击定位，拖动选择试听区间，双击空轨导入音频。也可用方向键定位、Shift 选择。")
        watch_theme(self)

    def set_data(self, a, b, duration, lengths=None):
        self.peaks = [a, b]
        self.lengths = lengths or [duration, duration]
        self.duration = duration
        self._key_anchor = None
        self._key_position = None
        self.update()

    def point_time(self, x):
        return max(0, min(1, (x - 13) / max(1, self.width() - 26))) * self.duration

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
            self._key_anchor = None
            self._key_position = None
            self.anchor = self.point_time(e.position().x())

    def mouseReleaseEvent(self, e):
        if self.anchor is None:
            return
        end = self.point_time(e.position().x())
        if abs(end - self.anchor) > max(0.04, self.duration * 0.007):
            self.region = tuple(sorted((end, self.anchor)))
            self.selected.emit(*self.region)
        else:
            self.region = None
            self.seek.emit(end)
        self.anchor = None
        self.update()

    def mouseDoubleClickEvent(self, e):
        if not self.duration:
            self.import_requested.emit()

    def keyPressEvent(self, event):
        key = event.key()
        if not self.duration and key in (Qt.Key_Return, Qt.Key_Enter):
            self.import_requested.emit()
            event.accept()
            return
        if key not in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End) or not self.duration:
            return super().keyPressEvent(event)
        if self.region is None:
            self._key_anchor = self._key_position = None
        old = self._key_position if self._key_position is not None else self.cursor
        step = 1.0 if event.modifiers() & Qt.ControlModifier else 0.1
        target = {Qt.Key_Home: 0.0, Qt.Key_End: self.duration}.get(
            key, old + (-step if key == Qt.Key_Left else step))
        self.cursor = max(0.0, min(self.duration, target))
        if event.modifiers() & Qt.ShiftModifier:
            if self._key_anchor is None:
                self._key_anchor = old
            self._key_position = self.cursor
            self.region = tuple(sorted((self._key_anchor, self.cursor)))
            self.selected.emit(*self.region)
        else:
            self._key_anchor = None
            self._key_position = None
            self.region = None
            self.seek.emit(self.cursor)
        self.update()
        event.accept()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), theme_color("canvas"))
        w, h = self.width(), self.height()
        left, span = 13, max(1, w - 26)
        p.setFont(self.font())
        for i in range(9):
            x = int(left + span * i / 8)
            p.setPen(theme_color("grid"))
            p.drawLine(x, 25, x, h - 7)
            if i < 8:
                p.setPen(theme_color("muted"))
                p.drawText(x, 18, timecode(self.duration * i / 8)[:5] if self.duration else "·")
        for row, (peak, token, name) in enumerate(
            zip(self.peaks, ["wave_a", "wave_b"], ["原始录音", "调音输出"])
        ):
            top = 27 + (h - 28) * row / 2
            bottom = 27 + (h - 28) * (row + 1) / 2
            middle = (top + bottom + 10) / 2
            p.setPen(theme_color(token))
            p.drawText(left, round(top + 14), name)
            p.setPen(theme_color("grid"))
            p.drawLine(left, int(middle), w - left, int(middle))
            if peak is not None:
                # Draw vertical min/max pairs so isolated transients survive downsampling.
                lane_span = span * self.lengths[row] / max(self.duration, 1e-9)
                n = max(1, min(len(peak), round(lane_span)))
                indices = np.linspace(0, len(peak), n + 1, dtype=int)
                lo = np.minimum.reduceat(peak[:, 0], indices[:-1])
                hi = np.maximum.reduceat(peak[:, 1], indices[:-1])
                amp = (bottom - top - 22) * 0.47
                p.setPen(QPen(theme_color(token), max(1.0, lane_span / n)))
                for j in range(n):
                    x = left + lane_span * (j + 0.5) / n
                    p.drawLine(
                        QPointF(x, middle - amp * float(hi[j])),
                        QPointF(x, middle - amp * float(lo[j])),
                    )
            elif row == 0:
                p.fillRect(QRectF(w * 0.22, middle - 13, w * 0.56, 25), theme_color("canvas"))
                p.setPen(theme_color("muted"))
                p.drawText(QRectF(0, middle - 13, w, 26), Qt.AlignCenter, "拖入录音以显示波形")
        if self.duration:
            if self.region:
                a, b = self.region
                overlay = theme_color("accent")
                overlay.setAlpha(36)
                bounds = QRectF(left + span * a / self.duration, 25,
                                span * (b - a) / self.duration, h - 26)
                p.fillRect(bounds, overlay)
                p.setPen(QPen(theme_color("focus"), 1.5, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(bounds)
            x = left + span * min(1, self.cursor / self.duration)
            p.setPen(QPen(theme_color("cursor"), 1))
            p.drawLine(QPointF(x, 23), QPointF(x, h))
        if self.hasFocus():
            p.setPen(QPen(theme_color("focus"), 2))
            p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.end()


class Spectrum(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(55)
        self.setMaximumHeight(105)
        self.setAccessibleName("监听频谱")
        self.setAccessibleDescription("32 Hz 至 20 kHz 监听信号频谱；仅显示，不影响导出。")
        self.values = np.full(48, -90.0)
        self.edges = np.geomspace(32, 20000, 49)
        self.hann = np.hanning(2048)
        self.index = np.clip((self.edges / 44100 * 2048).astype(int), 1, 1024)
        watch_theme(self)

    def update_audio(self, block):
        if len(block) < 2:
            self.values.fill(-90)
        else:
            mono = block[:2048].mean(axis=1)
            fft = np.abs(np.fft.rfft(mono * np.hanning(len(mono)), n=2048)) * 4 / len(mono)
            for j, (a, b) in enumerate(zip(self.index, self.index[1:])):
                self.values[j] = 20 * np.log10(max(1e-6, float(fft[a : max(b, a + 1)].max())))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), theme_color("canvas"))
        for i, db in enumerate(self.values):
            amp = np.clip((db + 80) / 80, 0, 1) * (h - 21)
            p.fillRect(
                QRectF(i * w / 48 + 1, h - 16 - amp, max(1, w / 48 - 3), max(1, amp)),
                theme_color("wave_b" if i < 24 else "wave_a"),
            )
        p.setFont(self.font())
        p.setPen(theme_color("muted"))
        for frac, label in [(0, "32 Hz"), (0.28, "200"), (0.53, "1k"), (0.77, "5k"), (0.91, "20k")]:
            p.drawText(int(w * frac) + 2, h - 2, label)
        p.end()
