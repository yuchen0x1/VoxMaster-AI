from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .studio_session import TRACKS, duration, new_clip
from .theme import color, watch_theme


TRACK_LABELS = {"Vocal": "人声", "Instrumental": "伴奏", "FX": "效果", "Master": "主总线"}
# Retained for callers that imported the original, dark-theme palette.
COLORS = {
    "Vocal": "#AB93FE",
    "Instrumental": "#65BCDE",
    "FX": "#D5A963",
    "Master": "#A3D5C2",
}
TRACK_COLOR_TOKENS = {
    "Vocal": "track_vocal",
    "Instrumental": "track_music",
    "FX": "track_fx",
    "Master": "accent",
}


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
        self.setAccessibleDescription(
            "左右方向键移动光标，按住 Shift 快速移动；Home 和 End 跳到开头和结尾。"
            "单击定位，拖动选区，右键编辑。"
        )
        self.setToolTip(
            "单击定位，拖动选区，右键编辑；←/→ 移动，Shift+←/→ 快进，Home/End 跳转"
        )
        watch_theme(self)

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

    def keyPressEvent(self, e):
        if e.key() not in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End):
            super().keyPressEvent(e)
            return
        if e.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            super().keyPressEvent(e)
            return

        self.seek_requested.emit()
        if e.key() == Qt.Key_Home:
            target = 0
        elif e.key() == Qt.Key_End:
            target = self.total
        else:
            seconds = 1.0 if e.modifiers() & Qt.ShiftModifier else 0.1
            step = max(1, round(self.session.sr * seconds))
            direction = -1 if e.key() == Qt.Key_Left else 1
            target = int(np.clip(self.cursor + direction * step, 0, self.total))
        self.cursor = self.first = self.last = target
        offset = int(np.clip(target - self.span if target > self.offset + self.span
                             else min(self.offset, target), 0, self.total - self.span))
        if offset != self.offset:
            self.offset = offset
            self.view_changed.emit()
        self.selection_changed.emit()
        self.update()
        e.accept()

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
        p.fillRect(self.rect(), color("canvas"))
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
            p.setPen(color("grid"))
            p.drawLine(QPointF(x, self.top - 4), QPointF(x, self.height()))
            p.setPen(color("muted"))
            label = clock_text(t, sr)
            if x + p.fontMetrics().horizontalAdvance(label) + 5 < self.width():
                p.drawText(QPointF(x + 3, self.top - 9), label)
        selection_bounds = None
        if self.last > self.first:
            row = TRACKS.index(self.lane)
            left = max(self.left, self.x_for(self.first))
            right = min(self.width(), self.x_for(self.last))
            if right > left:
                selection_bounds = QRectF(left, self.top + row * row_h, right - left, row_h)
                selection = color("selected")
                selection.setAlpha(110)
                p.fillRect(selection_bounds, selection)
        for i, name in enumerate((*TRACKS, "Master")):
            y = self.top + i * row_h
            mid = y + row_h / 2
            col = color(TRACK_COLOR_TOKENS[name])
            p.fillRect(
                QRectF(0, y, self.left - 1, row_h - 1),
                color("selected" if name == self.lane else "panel"),
            )
            if self.lane == name:
                p.fillRect(QRectF(0, y, 3, row_h - 1), col)
            p.setPen(color("on_selected") if self.lane == name else col)
            p.drawText(QPointF(12, mid - 2), TRACK_LABELS[name])
            p.setPen(color("muted"))
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
            p.setPen(color("border"))
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
                    p.setPen(QPen(color("band_low"), 1.5))
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
        if selection_bounds is not None:
            p.setPen(QPen(color("focus"), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(selection_bounds)
        cursor_x = self.x_for(self.cursor)
        if self.left <= cursor_x <= self.width():
            cursor_x = min(cursor_x, self.width() - 1)
            p.setPen(QPen(color("cursor"), 2))
            p.drawLine(QPointF(cursor_x, self.top - 2), QPointF(cursor_x, self.height()))
        if self.hasFocus():
            p.setPen(QPen(color("focus"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.end()
