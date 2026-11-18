"""Qt painting for the timeline and transport meters."""

import numpy as np
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QIcon
from PySide6.QtWidgets import QWidget

STYLES = """
QWidget {background:#15151d;color:#ececf4;font-family:"Microsoft YaHei UI";font-size:13px;}
QMainWindow,QDialog {background:#13131a;}
QFrame#side,QFrame#side QWidget {background:#181821;}
QFrame#inspector,QFrame#inspector QWidget {background:#1c1c26;}
QLabel#brand {font-size:20px;font-weight:700;}
QLabel#title {font-size:26px;font-weight:650;}
QLabel#section {font-size:15px;font-weight:650;}
QLabel#sub {color:#b0b0c2;font-size:12px;}
QLabel#value {font-family:Consolas;color:#bcaaff;font-size:18px;}
QLabel#clock {font-family:Consolas;font-size:21px;color:#efeafd;}
QPushButton,QToolButton,QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit,QPlainTextEdit,QTextEdit,QListWidget,QTableWidget,QTreeWidget {background:#272733;color:#eeeeF8;border:1px solid #3b3b49;border-radius:5px;padding:5px 8px;}
QPushButton:hover,QToolButton:hover {background:#343442;border-color:#706b87;}
QPushButton:focus,QComboBox:focus,QLineEdit:focus,QSlider:focus {border:1px solid #ae94ff;}
QPushButton:disabled,QToolButton:disabled {color:#777788;background:#20202a;}
QPushButton#primary {background:#9e7dff;color:#181124;font-weight:700;padding:8px 16px;border:0;}
QPushButton#primary:hover {background:#b299ff;}
QPushButton#primary:disabled {background:#443952;color:#afa4be;}
QPushButton#nav {text-align:left;background:transparent;border:0;border-radius:5px;padding:8px 10px;color:#c3c1d1;}
QPushButton#nav:hover,QPushButton#nav:checked {background:#302a43;color:#d4bfff;}
QPushButton:checked {background:#403457;color:#e4d8ff;}
QFrame#rule {color:#33333f;background:#33333f;max-height:1px;min-height:1px;}
QScrollArea,QGroupBox {border:0;}
QTabWidget::pane {border:1px solid #363643;}
QTabBar::tab {background:#22222f;padding:7px 12px;}
QTabBar::tab:selected {background:#3a3051;color:#e1cfff;}
QSlider::groove:horizontal {height:4px;background:#383844;border-radius:2px;}
QSlider::sub-page:horizontal {background:#9274e2;border-radius:2px;}
QSlider::handle:horizontal {background:#d2c1ff;width:11px;margin:-4px 0;border-radius:5px;}
QProgressBar {border:0;background:#2a2935;color:#fff;}
QProgressBar::chunk {background:#9175e3;}
QToolTip {background:#282432;color:white;border:1px solid #736982;}
QMenu {background:#272733;} QMenu::item:selected {background:#514267;}
"""


def app_icon():
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#a989ff"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    p.setPen(QPen(QColor("#20132c"), 4, Qt.SolidLine, Qt.RoundCap))
    for i, height in enumerate([10, 22, 36, 24, 14]):
        x = 14 + i * 9
        p.drawLine(x, 32 - height // 2, x, 32 + height // 2)
    p.end()
    return QIcon(pix)


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
        self.setMinimumHeight(168)
        self.setToolTip("单击定位，拖动选择试听区间，双击空轨导入音频。")

    def set_data(self, a, b, duration, lengths=None):
        self.peaks = [a, b]
        self.lengths = lengths or [duration, duration]
        self.duration = duration
        self.update()

    def point_time(self, x):
        return max(0, min(1, (x - 13) / max(1, self.width() - 26))) * self.duration

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
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

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#111119"))
        w, h = self.width(), self.height()
        left, span = 13, max(1, w - 26)
        p.setFont(QFont("Consolas", 9))
        for i in range(9):
            x = int(left + span * i / 8)
            p.setPen(QColor("#292935"))
            p.drawLine(x, 25, x, h - 7)
            if i < 8:
                p.setPen(QColor("#9393a9"))
                p.drawText(x, 18, timecode(self.duration * i / 8)[:5] if self.duration else "·")
        for row, (peak, color, name) in enumerate(
            zip(self.peaks, ["#9984f2", "#70c4e1"], ["原始录音", "调音输出"])
        ):
            top = 27 + (h - 28) * row / 2
            bottom = 27 + (h - 28) * (row + 1) / 2
            middle = (top + bottom + 10) / 2
            p.setFont(QFont("Microsoft YaHei UI", 9))
            p.setPen(QColor(color))
            p.drawText(left, round(top + 14), name)
            p.setPen(QColor("#393643"))
            p.drawLine(left, int(middle), w - left, int(middle))
            if peak is not None:
                # Draw vertical min/max pairs so isolated transients survive downsampling.
                lane_span = span * self.lengths[row] / max(self.duration, 1e-9)
                n = max(1, min(len(peak), round(lane_span)))
                indices = np.linspace(0, len(peak), n + 1, dtype=int)
                lo = np.minimum.reduceat(peak[:, 0], indices[:-1])
                hi = np.maximum.reduceat(peak[:, 1], indices[:-1])
                amp = (bottom - top - 22) * 0.47
                p.setPen(QPen(QColor(color), max(1.0, lane_span / n)))
                for j in range(n):
                    x = left + lane_span * (j + 0.5) / n
                    p.drawLine(
                        QPointF(x, middle - amp * float(hi[j])),
                        QPointF(x, middle - amp * float(lo[j])),
                    )
            elif row == 0:
                p.fillRect(QRectF(w * 0.22, middle - 13, w * 0.56, 25), QColor("#111119"))
                p.setPen(QColor("#aaa6ba"))
                p.drawText(QRectF(0, middle - 13, w, 26), Qt.AlignCenter, "拖入录音以显示波形")
        if self.duration:
            if self.region:
                a, b = self.region
                p.fillRect(
                    QRectF(
                        left + span * a / self.duration, 25, span * (b - a) / self.duration, h - 25
                    ),
                    QColor(144, 109, 229, 38),
                )
            x = left + span * min(1, self.cursor / self.duration)
            p.setPen(QPen(QColor("#f2eaff"), 1))
            p.drawLine(QPointF(x, 23), QPointF(x, h))
        p.end()


class Spectrum(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(55)
        self.setMaximumHeight(105)
        self.values = np.full(48, -90.0)
        self.edges = np.geomspace(32, 20000, 49)
        self.hann = np.hanning(2048)
        self.index = np.clip((self.edges / 44100 * 2048).astype(int), 1, 1024)

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
        p.fillRect(self.rect(), QColor("#171720"))
        for i, db in enumerate(self.values):
            amp = np.clip((db + 80) / 80, 0, 1) * (h - 21)
            p.fillRect(
                QRectF(i * w / 48 + 1, h - 16 - amp, max(1, w / 48 - 3), max(1, amp)),
                QColor.fromRgbF(0.43 + i * 0.004, 0.65 - i * 0.004, 0.86),
            )
        p.setFont(QFont("Consolas", 9))
        p.setPen(QColor("#a5a4b3"))
        for frac, label in [(0, "32 Hz"), (0.28, "200"), (0.53, "1k"), (0.77, "5k"), (0.91, "20k")]:
            p.drawText(int(w * frac) + 2, h - 2, label)
        p.end()
