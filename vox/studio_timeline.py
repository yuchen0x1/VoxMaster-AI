from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .studio_session import TRACKS, duration, new_clip


TRACK_LABELS = {"Vocal": "人声", "Instrumental": "伴奏", "FX": "效果", "Master": "主总线"}
COLORS = {"Vocal": "#AB93FE", "Instrumental": "#65BCDE", "FX": "#D5A963", "Master": "#A3D5C2"}


def clock_text(frame, rate):
    hundredths = round(max(0, int(frame)) * 100 / rate)
    minutes, remainder = divmod(hundredths, 6000)
    seconds, fraction = divmod(remainder, 100)
    return f"{minutes:02d}:{seconds:02d}.{fraction:02d}"


class Timeline(QWidget):
    selection_changed = Signal()
    seek_requested = Signal()
    lane_changed = Signal(str)
    menu_requested = Signal(object)
    view_changed = Signal()
    left = 84
    top = 28

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.lane = "Vocal"
        self.cursor = self.first = self.last = self.offset = 0
        self.zoom = 1.0
        self.wave_gain = 1
        self._anchor = 0
        self._dragging = False
        self._thumbs = {}
        self.master_audio = None
        self.master_version = 0
        self.setMinimumSize(360, 208)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("多轨时间轴")
        self.setToolTip("单击定位，拖动选区，右键编辑")

    @property
    def total(self):
        return max(self.session.sr, self.session.frames)

    @property
    def span(self):
        return max(1, int(self.total / self.zoom))

    def x_for(self, sample):
        return self.left + (sample - self.offset) * (self.width() - self.left) / self.span

    def sample_for(self, x):
        return int(
            np.clip(
                self.offset + (x - self.left) * self.span / max(1, self.width() - self.left),
                0,
                self.total,
            )
        )

    def change_zoom(self, factor):
        before = (self.cursor - self.offset) / self.span
        self.zoom = float(np.clip(self.zoom * factor, 1.0, 128.0))
        self.offset = int(np.clip(self.cursor - before * self.span, 0, self.total - self.span))
        self.view_changed.emit()
        self.update()

    def mousePressEvent(self, e):
        row = int((e.position().y() - self.top) // self.row_height())
        if row == len(TRACKS):
            if e.button() == Qt.LeftButton and e.position().x() >= self.left:
                self.seek_requested.emit()
                self.cursor = self.first = self.last = self.sample_for(e.position().x())
                self.selection_changed.emit()
                self.update()
            return
        if 0 <= row < len(TRACKS):
            self.lane = TRACKS[row]
            self.lane_changed.emit(self.lane)
        if e.button() == Qt.RightButton:
            self.menu_requested.emit(e.globalPosition().toPoint())
        elif e.button() == Qt.LeftButton and e.position().x() >= self.left:
            self.seek_requested.emit()
            self._dragging = True
            self.cursor = self._anchor = self.sample_for(e.position().x())
            self.first = self.last = self.cursor
            self.selection_changed.emit()
        self.update()

    def mouseMoveEvent(self, e):
        if self._dragging and e.buttons() & Qt.LeftButton:
            end = self.sample_for(e.position().x())
            self.first, self.last = sorted([self._anchor, end])
            self.selection_changed.emit()
            self.update()

    def mouseReleaseEvent(self, e):
        self._dragging = False

    def mouseDoubleClickEvent(self, e):
        row = int((e.position().y() - self.top) // self.row_height())
        if 0 <= row < len(TRACKS) and e.button() == Qt.LeftButton and e.position().x() >= self.left:
            sample = self.sample_for(e.position().x())
            for clip in self.session.strip(self.lane)["clips"]:
                if clip["at"] <= sample < clip["at"] + duration(clip):
                    self.cursor = self.first = clip["at"]
                    self.last = self.first + duration(clip)
                    self.selection_changed.emit()
                    self.update()
                    break

    def row_height(self):
        return (self.height() - self.top) / 4.0

    def set_master(self, audio):
        self.master_audio = audio
        self.master_version += 1
        self.update()

    def _envelope(self, clip, count, lo, hi):
        master = clip["source"] == "Master"
        source = self.master_audio if master else self.session.sources[clip["source"]]
        key = (
            "Master" if master else id(source),
            self.master_version if master else 0,
            lo,
            hi,
            count,
        )
        if key not in self._thumbs:
            edges = np.linspace(lo, hi, min(hi - lo, count) + 1, dtype=np.int64)
            low, high = [], []
            for a, b in zip(edges[:-1], edges[1:]):
                samples = source[a:b]
                low.append(min(0.0, float(samples.min())))
                high.append(max(0.0, float(samples.max())))
            if len(self._thumbs) > 96:
                self._thumbs.clear()
            self._thumbs[key] = (low, high)
        return self._thumbs[key]

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#13151D"))
        row_h = self.row_height()
        sr = self.session.sr
        sec_step = self.span / sr / max(2, (self.width() - self.left) // 94)
        power = 10 ** math.floor(math.log10(max(0.001, sec_step)))
        step = next(k * power for k in (1, 2, 5, 10) if k * power >= sec_step)
        step_frames = max(1, round(step * sr))
        for t in range(
            (self.offset // step_frames) * step_frames, self.offset + self.span + 1, step_frames
        ):
            x = self.x_for(t)
            if x < self.left:
                continue
            p.setPen(QColor("#323641"))
            p.drawLine(QPointF(x, self.top - 4), QPointF(x, self.height()))
            p.setPen(QColor("#ACB0C2"))
            label = clock_text(t, sr)
            if x + p.fontMetrics().horizontalAdvance(label) + 5 < self.width():
                p.drawText(QPointF(x + 3, self.top - 9), label)
        for i, name in enumerate((*TRACKS, "Master")):
            y = self.top + i * row_h
            mid = y + row_h / 2
            col = QColor(COLORS[name])
            p.fillRect(
                QRectF(0, y, self.left - 1, row_h - 1),
                QColor("#282634" if name == self.lane else "#1B1E27"),
            )
            if self.lane == name:
                p.fillRect(QRectF(0, y, 3, row_h - 1), col)
            p.setPen(col)
            p.drawText(QPointF(12, mid - 2), TRACK_LABELS[name])
            p.setPen(QColor("#A7ACBA"))
            if name == "Master":
                clips = (
                    []
                    if self.master_audio is None
                    else [new_clip("Master", 0, len(self.master_audio))]
                )
                gain = self.session.state["master_db"]
            else:
                strip = self.session.strip(name)
                clips = strip["clips"]
                gain = strip["gain"]
            p.drawText(QPointF(12, mid + 17), f"{gain:+.1f} dB")
            p.setPen(QColor("#363A48"))
            p.drawLine(QPointF(self.left, y), QPointF(self.width(), y))
            for c in clips:
                a = max(self.offset, c["at"])
                b = min(self.offset + self.span, c["at"] + duration(c))
                if a >= b:
                    continue
                left, right = self.x_for(a), self.x_for(b)
                # Clip bodies and source peak envelopes use the identical frame-to-pixel transform.
                base = QColor(col)
                base.setAlpha(38)
                p.fillRect(QRectF(left, y + 5, max(1.0, right - left), row_h - 10), base)
                p.fillRect(QRectF(left, y + 5, 1, row_h - 10), col)
                p.setPen(QPen(col, 1))
                lo = c["start"] + a - c["at"]
                hi = lo + b - a
                low, high = self._envelope(c, max(1, int(right - left)), lo, hi)
                path = QPainterPath()
                for j, (vmin, vmax) in enumerate(zip(low, high)):
                    x = left + (j + 0.5) * (right - left) / len(low)
                    path.moveTo(x, mid - min(1, vmax * self.wave_gain) * row_h * 0.37)
                    path.lineTo(x, mid - max(-1, vmin * self.wave_gain) * row_h * 0.37 + 0.5)
                p.drawPath(path)
                if c["env"]:
                    p.save()
                    p.setClipRect(QRectF(left, y, right - left, row_h))
                    p.setPen(QPen(QColor("#F4C275"), 1.5))
                    curve = QPainterPath()
                    for n, (offset, value) in enumerate(c["env"]):
                        x = self.x_for(c["at"] + offset)
                        h = y + row_h - 7 - min(1.0, value / 2.0) * (row_h - 14)
                        if n == 0:
                            curve.moveTo(x, h)
                        else:
                            curve.lineTo(x, h)
                    p.drawPath(curve)
                    p.restore()
        if self.last > self.first:
            row = TRACKS.index(self.lane)
            left = max(self.left, self.x_for(self.first))
            right = min(self.width(), self.x_for(self.last))
            if right > left:
                p.fillRect(
                    QRectF(left, self.top + row * row_h, right - left, row_h),
                    QColor(195, 182, 255, 56),
                )
        cursor_x = self.x_for(self.cursor)
        if self.left <= cursor_x <= self.width():
            p.setPen(QPen(QColor("#FCF1B9"), 2))
            p.drawLine(QPointF(cursor_x, self.top - 2), QPointF(cursor_x, self.height()))
        p.end()
