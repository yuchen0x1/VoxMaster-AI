"""Native editable filter response and measured dynamics for the studio."""

import math
from threading import Event
import numpy as np
from scipy import signal
from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool, QRectF, QPointF, QTimer
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QDoubleSpinBox, QHBoxLayout
from . import engine
from .theme import color as theme_color, watch_theme

# Legacy public metadata; painting resolves semantic tokens, never these colors.
BANDS = (
    ("body", "厚度", "#b29aff"),
    ("mud", "低中频", "#9675ff"),
    ("presence", "清晰", "#6ca4ff"),
    ("air", "空气", "#72d0e5"),
)
BAND_TOKENS = {"body": "band_low", "mud": "band_mid", "presence": "band_high", "air": "band_high"}


class EqEditor(QWidget):
    """Graph edits the same spin boxes used by numeric/keyboard input."""

    def __init__(self, inputs, sr):
        super().__init__()
        self.inputs, self.sr = inputs, sr
        self.drag_band = None
        self.setMinimumHeight(215)
        self.setMouseTracking(True)
        self.setAccessibleName("均衡器频响曲线")
        self.setAccessibleDescription(
            "横轴为频率 Hz，纵轴为增益 dB。控制点标有频段名称；"
            "可拖动控制点，或在处理参数页用键盘编辑对应频率和增益。"
        )
        watch_theme(self)
        for k in inputs:
            if k in ("eq_q", "highpass_hz") or any(k.startswith(b[0] + "_") for b in BANDS):
                inputs[k].valueChanged.connect(self.update)

    def plot(self):
        return QRectF(38, 22, max(20, self.width() - 60), max(20, self.height() - 54))

    def xcoord(self, hz):
        r = self.plot()
        return r.left() + math.log(hz / 30) / math.log(20000 / 30) * r.width()

    def ycoord(self, gain):
        r = self.plot()
        return r.center().y() - gain * r.height() / 24

    def points(self):
        return [
            QPointF(
                self.xcoord(self.inputs[b + "_hz"].value()),
                self.ycoord(self.inputs[b + "_db"].value()),
            )
            for b, _, _ in BANDS
        ]

    def nearest(self, pos):
        return min(range(4), key=lambda i: (self.points()[i] - pos).manhattanLength())

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        i = self.nearest(event.position())
        if (self.points()[i] - event.position()).manhattanLength() < 25:
            self.drag_band = BANDS[i][0]
            self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        self.drag_band = None
        self.unsetCursor()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self.drag_band:
            r = self.plot()
            self.inputs[self.drag_band + "_hz"].setValue(
                30 * (20000 / 30) ** ((pos.x() - r.left()) / r.width())
            )
            self.inputs[self.drag_band + "_db"].setValue((r.center().y() - pos.y()) * 24 / r.height())
        else:
            close = (self.points()[self.nearest(pos)] - pos).manhattanLength() < 25
            self.setCursor(Qt.OpenHandCursor if close else Qt.ArrowCursor)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), theme_color("canvas"))
        r = self.plot()
        for gain in (-12, -6, 0, 6, 12):
            y = self.ycoord(gain)
            painter.setPen(theme_color("grid_strong" if gain == 0 else "grid"))
            painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            painter.setPen(theme_color("muted"))
            painter.drawText(QPointF(4, y + 4), str(gain))
        for f in (50, 100, 300, 1000, 3000, 10000):
            x = self.xcoord(f)
            painter.setPen(theme_color("grid"))
            painter.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            painter.setPen(theme_color("muted"))
            painter.drawText(
                QPointF(x - 9, r.bottom() + 20), str(f) if f < 1000 else str(f // 1000) + "k"
            )
        freq = np.geomspace(30, min(20000, 0.49 * self.sr), 320)
        p = {k: w.value() for k, w in self.inputs.items()}
        _, resp = signal.sosfreqz(engine.eq_sos(self.sr, p), freq, fs=self.sr)
        path = QPainterPath()
        for i, (f, v) in enumerate(zip(freq, 20 * np.log10(np.maximum(abs(resp), 1e-9)))):
            point = QPointF(self.xcoord(f), self.ycoord(np.clip(v, -12, 12)))
            if i:
                path.lineTo(point)
            else:
                path.moveTo(point)
        painter.setPen(QPen(theme_color("accent"), 2.5))
        painter.drawPath(path)
        painter.setPen(theme_color("accent"))
        painter.drawLine(QPointF(r.left(), r.top() - 8), QPointF(r.left() + 18, r.top() - 8))
        painter.setPen(theme_color("text"))
        painter.drawText(QPointF(r.left() + 24, r.top() - 4), "EQ 总响应")
        for point, (key, name, _) in zip(self.points(), BANDS):
            band_color = theme_color(BAND_TOKENS[key])
            painter.setBrush(band_color)
            painter.setPen(theme_color("canvas"))
            painter.drawEllipse(point, 6, 6)
            painter.setPen(band_color)
            painter.drawText(point + QPointF(7, -8), name)


class Trace(QWidget):
    def __init__(self, caption, color_token="wave_a"):
        super().__init__()
        self.caption = caption
        self.color_token = color_token
        self.points = np.empty((0, 2))
        self.xspan = (0, 1)
        self.yspan = (0, 1)
        self.setMinimumHeight(90)
        self.setAccessibleName(caption)
        self.setAccessibleDescription("横轴为时间（秒）；纵轴单位见图表标题。")
        watch_theme(self)

    def show_data(self, t, v, xspan, yspan):
        self.points = np.column_stack((t, v))
        self.xspan = xspan
        self.yspan = yspan
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.fillRect(self.rect(), theme_color("canvas"))
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(theme_color("text"))
        painter.drawText(QPointF(8, 16), self.caption)
        left, top = 9, 24
        width = max(1, self.width() - 20)
        height = max(1, self.height() - 45)
        painter.setPen(theme_color("grid_strong"))
        painter.drawLine(left, top, left + width, top)
        painter.setPen(theme_color("grid"))
        painter.drawLine(left, top + height, left + width, top + height)
        path = QPainterPath()
        connected = False
        a, b = self.xspan
        low, high = self.yspan
        for t, val in self.points:
            if not np.isfinite(val):
                connected = False
                continue
            pos = QPointF(
                left + width * (t - a) / max(0.001, b - a),
                top + height * (1 - np.clip((val - low) / max(0.01, high - low), 0, 1)),
            )
            if connected:
                path.lineTo(pos)
            else:
                path.moveTo(pos)
            connected = True
        painter.setPen(QPen(theme_color(self.color_token), 1.5))
        painter.drawPath(path)
        painter.setPen(theme_color("muted"))
        painter.drawText(QPointF(left, self.height() - 5), f"{a:.2f} s")
        painter.drawText(QPointF(left + width - 54, self.height() - 5), f"{b:.2f} s")


class Completion(QObject):
    received = Signal(object)


class Measure(QRunnable):
    def __init__(self, audio, sr, params, event, recipient):
        super().__init__()
        self.audio, self.sr, self.params, self.event, self.recipient = (
            audio,
            sr,
            params,
            event,
            recipient,
        )

    def run(self):
        try:
            p = self.params.copy()
            if "compress" in p["disabled"]:
                result = (self.event, np.array([0.0]), np.array([0.0]), "压缩器已旁通")
            else:
                before = p["order"][: p["order"].index("compress")]
                p["disabled"] = [k for k in engine.STAGES if k not in before or k in p["disabled"]]
                x = engine.process(self.audio, self.sr, p, self.event)
                hop, gr = engine.compression_curve(x, self.sr, p, self.event)
                result = (
                    self.event,
                    np.arange(len(gr)) * hop / self.sr,
                    -gr,
                    f"最大衰减 {np.max(gr):.1f} dB",
                )
        except Exception as exc:
            result = (self.event, np.array([]), np.array([]), str(exc))
        if not self.event.is_set():
            self.recipient.received.emit(result)


class MeterPanel(QWidget):
    def __init__(self, audio, sr, report, cursor, params):
        super().__init__()
        self.audio, self.sr, self.report, self.params = audio, sr, report, params
        self.task_cancel = None
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        start_label = QLabel("分析区域起点")
        self.start = QDoubleSpinBox()
        start_label.setBuddy(self.start)
        self.start.setAccessibleName("分析区域起点")
        self.start.setRange(0, max(0, len(audio) / sr - 0.02))
        self.start.setSuffix(" s")
        self.start.setValue(cursor)
        row.addWidget(start_label)
        self.start.valueChanged.connect(lambda _: self.schedule())
        row.addWidget(self.start)
        row.addStretch()
        layout.addLayout(row)
        self.pitch = Trace("原音基频 · Hz", "wave_a")
        self.gr = Trace("当前链路的压缩增益变化 · dB", "warning")
        self.info = QLabel()
        layout.addWidget(self.pitch, 1)
        layout.addWidget(self.gr, 1)
        layout.addWidget(self.info)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.measure)
        self.recipient = Completion()
        self.recipient.received.connect(self.finish)
        self.time_array = np.array(report.get("pitch_curve", []), dtype=float).reshape(-1, 2)

    def cancel(self):
        self.timer.stop()
        if self.task_cancel:
            self.task_cancel.set()

    def schedule(self):
        self.cancel()
        if self.isVisible():
            self.timer.start(150)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start(40)

    def hideEvent(self, event):
        self.cancel()
        super().hideEvent(event)

    def measure(self):
        a = int(self.start.value() * self.sr)
        segment = self.audio[a : a + 3 * self.sr]
        span = (a / self.sr, (a + len(segment)) / self.sr)
        first, last = np.searchsorted(self.time_array[:, 0], span)
        hz = self.time_array[first:last, 1]
        self.pitch.caption = (
            f"原音基频 · {np.min(hz[hz > 0]):.0f}–{np.max(hz):.0f} Hz"
            if np.any(hz)
            else "此区域未识别稳定基频"
        )
        self.pitch.show_data(
            self.time_array[first:last, 0],
            np.where(hz > 0, hz, np.nan),
            span,
            (50, max(420, np.max(hz, initial=0))),
        )
        self.info.setText("正在测量所选的 3 秒音频…")
        self.task_cancel = Event()
        from .tail011 import slice_params
        p = slice_params(self.params(), *span)
        QThreadPool.globalInstance().start(
            Measure(segment, self.sr, p, self.task_cancel, self.recipient)
        )

    def finish(self, result):
        event, t, g, text = result
        if self.task_cancel is not event or event.is_set():
            return
        start = self.start.value()
        self.gr.show_data(
            t + start,
            g,
            (start, min(start + 3, len(self.audio) / self.sr)),
            (min(-6, np.min(g, initial=0)), 0),
        )
        self.info.setText(text)
