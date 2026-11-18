"""Native selection editor for pitch and phrase-local effects."""

from copy import deepcopy

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from sounddevice import PortAudioError

from . import engine
from .analysis import loudness, pitch_track
from .jobs import Worker
from .playback import Playback
from .tail011 import guard_end, slice_params, validate_edits


class PitchCanvas(QWidget):
    selection = Signal(float, float)

    def __init__(self, curve, duration):
        super().__init__()
        self.original = np.array(curve, dtype=float).reshape(-1, 2)
        self.after = np.empty((0, 2))
        self.duration = duration
        self.view = (0.0, duration)
        self.range = (0.0, min(duration, 0.5))
        self.anchor = None
        self.setMinimumHeight(98)
        self.setAccessibleName("音高曲线。拖动选择时间区间，或使用下方数值输入。")

    def xpos(self, t):
        a, b = self.view
        return 38 + (self.width() - 48) * (t - a) / max(0.001, b - a)

    def time_at(self, x):
        a, b = self.view
        return float(np.clip(a + (x - 38) * (b - a) / max(1, self.width() - 48), a, b))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.anchor = self.time_at(event.position().x())

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            self.range = tuple(
                sorted((self.anchor, self.time_at(event.position().x())))
            )
            self.update()

    def mouseReleaseEvent(self, event):
        if self.anchor is not None:
            a, b = sorted((self.anchor, self.time_at(event.position().x())))
            self.anchor = None
            if b - a >= 0.02:
                self.selection.emit(a, b)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#131621"))
        low, high = self.view
        h = self.height() - 20

        def y(freq):
            return h - 5 - (h - 10) * np.clip(np.log2(freq / 64) / 3.45, 0, 1)

        painter.setPen(QPen(QColor("#333a48")))
        for hz in (100, 200, 400):
            line = int(y(hz))
            painter.drawLine(35, line, self.width() - 8, line)
            painter.drawText(3, line + 3, str(hz))
        painter.fillRect(
            QRectF(
                self.xpos(self.range[0]),
                0,
                self.xpos(self.range[1]) - self.xpos(self.range[0]),
                h,
            ),
            QColor(137, 92, 228, 55),
        )
        for curve, colour in ((self.original, "#8bb7fc"), (self.after, "#df98ef")):
            first, last = np.searchsorted(curve[:, 0], [low, high])
            chunk = curve[first:last]
            path = QPainterPath()
            linked = False
            for t, hz in chunk[:: max(1, len(chunk) // max(1, self.width() * 3))]:
                if hz <= 0:
                    linked = False
                    continue
                point = QPointF(self.xpos(t), y(hz))
                if linked:
                    path.lineTo(point)
                else:
                    path.moveTo(point)
                linked = True
            painter.setPen(QPen(QColor(colour), 1.6))
            painter.drawPath(path)
        painter.setPen(QColor("#a9b2c7"))
        painter.drawText(37, self.height() - 3, f"{low:.2f} s")
        painter.drawText(self.width() - 80, self.height() - 3, f"{high:.2f} s")


def number(low, high, value, step, suffix=""):
    box = QDoubleSpinBox()
    box.setDecimals(3 if step < 0.01 else 2)
    box.setRange(low, high)
    box.setSingleStep(step)
    box.setValue(value)
    box.setSuffix(suffix)
    return box


class PitchTailEditor(QWidget):
    def __init__(self, audio, sr, report, params, get_params, parent=None):
        super().__init__(parent)
        self.audio, self.sr, self.report = audio, sr, report
        self.duration = len(audio) / sr
        self.get_params = get_params
        self.edits = {
            k: deepcopy(params.get(k, [])) for k in ("pitch_regions", "tail_regions")
        }
        self.history = []
        self.worker = None
        self.player = Playback()
        self.closing = False
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("拖动选择音高区间   ·   蓝色原音 / 紫色试听结果"))
        self.plot = PitchCanvas(report.get("pitch_curve", []), self.duration)
        self.plot.selection.connect(self.select)
        layout.addWidget(self.plot, 1)
        row = QHBoxLayout()
        self.begin = number(0, self.duration, 0, 0.001, " s")
        self.end = number(0, self.duration, min(0.5, self.duration), 0.001, " s")
        for label, box in (("起点", self.begin), ("终点", self.end)):
            row.addWidget(QLabel(label))
            row.addWidget(box)
            box.valueChanged.connect(self.selection_changed)
        self.button(row, "放大选区", self.zoom)
        self.button(row, "全曲", lambda: self.zoom(full=True))
        layout.addLayout(row)
        self.candidates = QComboBox()
        self.candidates.addItem("定位检测到的句尾…", None)
        for item in report.get("tail_candidates", []):
            if item["candidate"]:
                self.candidates.addItem(
                    f"{item['end']:.2f} s · {'拖腔' if item['sustained'] else '句尾'}"
                    f" · 空隙 {item['gap']:.2f} s",
                    item,
                )
        self.candidates.activated.connect(self.on_candidate)
        layout.addWidget(self.candidates)
        form = QFormLayout()
        self.pitch = number(-5, 5, 0, 0.1, " st")
        self.speed = number(10, 300, params["pitch_speed_ms"], 5, " ms")
        self.strength = number(0, 1, params["pitch_strength"], 0.05)
        self.stretch = number(0.5, 2, 1, 0.05, " ×")
        self.send = number(-36, 6, 0, 1, " dB")
        self.repeats = QSpinBox()
        self.repeats.setRange(0, 12)
        self.repeats.setValue(3)
        self.echo = number(0, 0.8, params["delay"], 0.02)
        self.verb = number(0, 0.8, params["reverb"], 0.02)
        for text, fields in (
            (
                "音高",
                (
                    ("半音", self.pitch),
                    ("速度", self.speed),
                    ("贴音力度", self.strength),
                ),
            ),
            (
                "尾音",
                (("时长", self.stretch), ("发送", self.send), ("重复", self.repeats)),
            ),
            ("空间", (("延迟发送", self.echo), ("混响发送", self.verb))),
        ):
            controls = QHBoxLayout()
            for caption, widget in fields:
                controls.addWidget(QLabel(caption))
                controls.addWidget(widget, 1)
            form.addRow(text, controls)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.button(row, "写入选区音高", lambda: self.commit("pitch_regions"))
        self.button(row, "写入选区尾音", lambda: self.commit("tail_regions"))
        self.button(row, "移除编辑", self.remove)
        self.button(row, "撤销编辑", self.undo)
        layout.addLayout(row)
        self.list = QListWidget()
        self.list.setMaximumHeight(76)
        self.list.currentRowChanged.connect(self.load_edit)
        layout.addWidget(self.list)
        row = QHBoxLayout()
        self.button(row, "A 原音", lambda: self.audition(False))
        self.button(row, "B 修正后", lambda: self.audition(True))
        self.button(row, "试听下一句", lambda: self.audition(True, next_phrase=True))
        self.button(row, "停止试听", self.stop)
        layout.addLayout(row)
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.refresh()
        self.selection_changed()

    @staticmethod
    def button(layout, text, action):
        b = QPushButton(text)
        b.clicked.connect(lambda checked=False: action())
        layout.addWidget(b)

    def select(self, a, b):
        self.begin.setValue(a)
        self.end.setValue(b)
        self.selection_changed()

    def selection_changed(self):
        a, b = self.begin.value(), self.end.value()
        self.plot.range = (a, b)
        self.plot.update()
        if not hasattr(self, "info"):
            return
        next_s = guard_end(self.report.get("tail_candidates", []), b, self.duration)
        if next_s >= self.duration:
            label = f"到轨道末尾剩余 {max(0.0, self.duration - b):.2f} s"
        elif next_s <= b:
            label = "选区终点仍有连续发声，延迟将限于选区内"
        else:
            label = f"下一句约 {next_s + 0.015:.2f} s 开始，可用延展 {next_s - b:.2f} s"
        curve = self.plot.original
        i, j = np.searchsorted(curve[:, 0], [a, b])
        scores = np.asarray(self.report.get("pitch_confidence", []))[i:j]
        scores = scores[scores > 0]
        confidence = (
            f" · 有声帧周期置信度中位数 {np.median(scores):.2f}" if len(scores) else ""
        )
        self.info.setText(label + confidence)

    def zoom(self, full=False):
        a, b = self.begin.value(), self.end.value()
        if full:
            self.plot.view = (0, self.duration)
        elif b > a:
            self.plot.view = (max(0, a - 0.1), min(self.duration, b + 0.1))
        self.plot.update()

    def on_candidate(self, index):
        item = self.candidates.itemData(index)
        if item:
            self.select(
                max(item["start"], item["end"] - (0.4 if item["sustained"] else 0.22)),
                item["end"],
            )

    def value(self):
        return deepcopy(self.edits)

    def commit(self, key):
        a, b = self.begin.value(), self.end.value()
        fields = (
            {
                "semitones": self.pitch.value(),
                "speed_ms": self.speed.value(),
                "strength": self.strength.value(),
            }
            if key == "pitch_regions"
            else {
                "stretch": self.stretch.value(),
                "gain_db": self.send.value(),
                "repeats": self.repeats.value(),
                "reverb": self.verb.value(),
                "delay": self.echo.value(),
            }
        )
        updated = self.value()
        updated[key] = [
            r
            for r in updated[key]
            if abs(r["start"] - a) > 0.0006 or abs(r["end"] - b) > 0.0006
        ]
        updated[key].append(dict(start=a, end=b, **fields))
        try:
            validate_edits(updated)
        except ValueError as exc:
            self.info.setText(str(exc))
            return
        self.remember()
        self.edits = updated
        self.refresh()
        self.info.setText("选区已写入。可试听当前结果，点击「应用」后渲染到工程。")

    def remember(self):
        self.history = (self.history + [self.value()])[-80:]
        self.stop()
        self.plot.after = np.empty((0, 2))
        self.plot.update()

    def undo(self):
        if self.history:
            self.stop()
            self.edits = self.history.pop()
            self.plot.after = np.empty((0, 2))
            self.plot.update()
            self.refresh()

    def refresh(self):
        self.list.clear()
        self.entries = []
        for key, title in (("pitch_regions", "音高"), ("tail_regions", "尾音")):
            for i, r in enumerate(self.edits[key]):
                value = (
                    f"{r['semitones']:+.2f} st"
                    if key == "pitch_regions"
                    else f"{r['stretch']:.2f} ×"
                )
                self.entries.append((key, i))
                self.list.addItem(
                    f"{title}   {r['start']:.3f} — {r['end']:.3f} s    {value}"
                )

    def load_edit(self, index):
        if index < 0:
            return
        key, i = self.entries[index]
        r = self.edits[key][i]
        self.select(r["start"], r["end"])
        pairs = (
            (
                (self.pitch, "semitones"),
                (self.speed, "speed_ms"),
                (self.strength, "strength"),
            )
            if key == "pitch_regions"
            else (
                (self.stretch, "stretch"),
                (self.send, "gain_db"),
                (self.echo, "delay"),
                (self.verb, "reverb"),
            )
        )
        for control, field in pairs:
            control.setValue(r[field])
        if key == "tail_regions":
            self.repeats.setValue(int(r["repeats"]))

    def remove(self):
        index = self.list.currentRow()
        if index >= 0:
            key, i = self.entries[index]
            self.remember()
            del self.edits[key][i]
            self.refresh()

    def stop(self):
        self.player.stop()
        if self.worker:
            self.worker.cancel.set()

    def shutdown(self, *args):
        self.closing = True
        self.stop()
        if self.worker:
            self.worker.wait()

    def hideEvent(self, event):
        self.stop()
        super().hideEvent(event)

    def audition(self, processed, next_phrase=False):
        self.player.stop()
        if self.worker:
            self.info.setText("正在准备试听，可点击停止。")
            return
        a, b = self.begin.value(), self.end.value()
        if a >= b:
            self.info.setText("终点须晚于起点")
            return
        anchor = max(0.0, a - 0.12)
        stop = min(self.duration, b + 0.75, anchor + 12)
        next_start = None
        if next_phrase:
            next_start = next(
                (
                    r["start"]
                    for r in self.report.get("tail_candidates", [])
                    if r["start"] > b + 0.005
                ),
                None,
            )
            if next_start is None:
                self.info.setText("该位置之后未检测到下一句")
                return
            anchor = max(0, min(max(a - 0.12, next_start - 8), next_start - 0.4))
            stop = min(self.duration, next_start + 0.85)
        left, right = round(anchor * self.sr), round(stop * self.sr)
        original = self.audio[left:right]
        if not len(original):
            return
        if not processed:
            self.play(
                original * min(1.0, 0.9 / max(1e-8, float(np.max(np.abs(original)))))
            )
            return
        settings = self.get_params()
        settings.update(self.value())
        p = slice_params(settings, left / self.sr, right / self.sr)
        p["disabled"] = list(
            set(p.get("disabled", [])) | (set(engine.STAGES) - {"pitch", "space"})
        )
        self.info.setText("正在渲染所选音高与空间效果…")

        def work(cancel, progress):
            out = engine.process(original, self.sr, p, cancel)
            times, hz = pitch_track(out, self.sr, cancel)
            impact = (
                "" if np.any(out != original) else " · 此试听区间未触发音高或空间处理"
            )
            # Use the original clip as the listening reference; preserve its
            # peak headroom, including float input above digital full scale.
            level_a, level_b = (
                loudness(original, self.sr, cancel),
                loudness(out, self.sr, cancel),
            )
            headroom = min(1.0, 0.9 / max(1e-8, float(np.max(np.abs(original)))))
            gain = (
                headroom * 10 ** (np.clip(level_a - level_b, -12, 12) / 20)
                if min(level_a, level_b) > -70
                else headroom
            )
            out = out * min(gain, 0.9 / max(1e-8, float(np.max(np.abs(out)))))
            if next_start is not None and "space" not in p["disabled"]:
                end_local = b - left / self.sr
                selected = [
                    r
                    for r in p.get("tail_regions", [])
                    if a - left / self.sr - 0.04 <= r["end"] <= end_local + 0.04
                ]
                marks = [
                    t
                    for t in p.get("tail_times", [])
                    if a - left / self.sr - 0.04 <= t <= end_local + 0.04
                ]
                probe = dict(
                    p,
                    dry=0,
                    tail_guard=True,
                    reverb_send="Tails",
                    reverb=p["reverb"] if p["reverb_send"] == "Tails" else 0.0,
                    tail_regions=selected,
                    tail_times=marks,
                    disabled=[s for s in engine.STAGES if s != "space"],
                )
                wet = engine.process(original, self.sr, probe, cancel)
                start = max(0, round(next_start * self.sr) - left)
                excerpt = wet[start : start + round(0.15 * self.sr)]
                if len(excerpt):
                    rms = np.sqrt(np.mean(excerpt**2))
                    impact = (
                        " · 下一句前 150 ms 内，所选尾音发送低于 −100 dBFS"
                        if rms < 1e-5
                        else f" · 下一句前 150 ms 内，所选尾音发送 {20 * np.log10(rms):.1f} dBFS RMS"
                    )
            return out, np.column_stack((times + left / self.sr, hz)), impact

        self.worker = Worker(work, self)
        self.worker.succeeded.connect(self.preview_ready)
        self.worker.failed.connect(self.info.setText)
        self.worker.finished.connect(self.worker_done)
        self.worker.start()

    def worker_done(self):
        if self.worker:
            self.worker.deleteLater()
            self.worker = None

    def preview_ready(self, result):
        if self.closing or not self.isVisible() or self.worker.cancel.is_set():
            return
        audio, self.plot.after, impact = result
        self.plot.update()
        self.play(audio)
        if impact:
            self.info.setText(self.info.text() + impact)

    def play(self, audio):
        try:
            host = self.window().parentWidget()
            if hasattr(host, "player"):
                self.player.device = host.player.device
            self.player.play(audio, self.sr)
            self.info.setText(f"正在试听 {len(audio) / self.sr:.2f} 秒")
        except (OSError, ValueError, RuntimeError, PortAudioError) as exc:
            self.info.setText(str(exc))
