"""Native multitrack editor and synchronized transport."""

from __future__ import annotations

import concurrent.futures
import copy
import math
import threading
import uuid
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QVBoxLayout,
    QWidget,
)

from .dialogs import managed_dialog
from .studio_session import Session, TRACKS, load_sources
from .studio_timeline import Timeline, TRACK_LABELS, clock_text


class StudioDialog(QDialog):
    def __init__(self, tracks, sr, parent=None, *, state=None):
        super().__init__(parent)
        from .playback import Playback

        self.player = Playback()
        if parent is not None and hasattr(parent, "player"):
            self.player.device = parent.player.device
            self.player.volume = parent.player.volume
        self.sr = int(sr)
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="VoxMix"
        )
        self.future = None
        self.cancel_job = threading.Event()
        self.after_job = None
        self.closing = False
        self.cache = None
        self.listen_mix = None
        self._mix_metrics = None
        self._refreshing = False
        self._active_preview = False
        self._heard_mix = None
        self._waiting_play = False
        self.monitor_future = None
        self.monitor_cancel = threading.Event()
        self.mix_timer = QTimer(self)
        self.mix_timer.setSingleShot(True)
        self.mix_timer.timeout.connect(self._queue_mix)
        self._loaded = True
        # A missing source is explicitly relinked before restoring the edit list.
        missing = bool(state and set(state.get("external_sources", {})) - set(tracks))
        self.session = Session(tracks, sr, None if missing else state)
        self.setWindowTitle("专业混音 · VoxMaster AI")
        self.resize(1056, 712)
        self.setMinimumSize(560, 420)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        shell.addWidget(scroll_area)
        contents = QWidget()
        scroll_area.setWidget(contents)
        root = QVBoxLayout(contents)
        root.setSpacing(8)
        root.setContentsMargins(20, 15, 20, 14)
        header = QHBoxLayout()
        title = QLabel("多轨混音")
        title.setStyleSheet("font-size: 23px; font-weight: 650;")
        header.addWidget(title)
        header.addStretch()
        self.balance_button = self._button(header, "自动平衡与响度…", self._balance)
        self.rack_button = self._button(header, "效果器链…", self._rack)
        header.addWidget(QLabel(f"{sr / 1000:g} kHz   /   立体声"))
        root.addLayout(header)
        self.tools = QWidget()
        toolbar = QHBoxLayout(self.tools)
        toolbar.setContentsMargins(0, 0, 0, 0)
        self.track_box = QComboBox()
        for t in TRACKS:
            self.track_box.addItem(TRACK_LABELS[t], t)
        self.track_box.setAccessibleName("选中轨道")
        self.track_box.currentIndexChanged.connect(self._choose_lane)
        toolbar.addWidget(self.track_box)
        self._button(
            toolbar,
            "添加音频…",
            self._import,
            "将新素材置入当前轨道光标处，覆盖重叠片段",
        )
        self._button(toolbar, "编辑 ▾", self._edit_menu)
        self.undo_button = self._button(toolbar, "撤销", lambda: self._undo(False))
        self.redo_button = self._button(toolbar, "重做", lambda: self._undo(True))
        toolbar.addStretch()
        wave_gain = QComboBox()
        wave_gain.setToolTip("调整波形垂直显示倍率")
        wave_gain.setAccessibleName("波形显示倍率")
        for value in (1, 2, 4, 8, 16, 32):
            wave_gain.addItem(f"波形 ×{value}", value)
        wave_gain.currentIndexChanged.connect(
            lambda _: self._set_wave_gain(wave_gain.currentData())
        )
        toolbar.addWidget(wave_gain)
        self._button(toolbar, "−", lambda: self.wave.change_zoom(0.5), "缩小时间轴")
        self._button(toolbar, "＋", lambda: self.wave.change_zoom(2), "放大时间轴")
        root.addWidget(self.tools)
        self.wave = Timeline(self.session)
        self.wave.lane_changed.connect(lambda t: self.track_box.setCurrentIndex(TRACKS.index(t)))
        self.wave.selection_changed.connect(self._selection)
        self.wave.seek_requested.connect(self._stop)
        self.wave.menu_requested.connect(self._menu_at)
        self.wave.view_changed.connect(self._view)
        root.addWidget(self.wave, 1)
        self.scroll = QScrollBar(Qt.Horizontal)
        self.scroll.setStyleSheet(
            "QScrollBar:horizontal{background:#1d2029;height:9px;border:0px;} QScrollBar::handle:horizontal{background:#666079;min-width:24px;border-radius:3px;} QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;} QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:transparent;}"
        )
        self.scroll.valueChanged.connect(self._scroll)
        root.addWidget(self.scroll)
        self.region = QLabel()
        root.addWidget(self.region)
        self.strips = QWidget()
        mixer = QGridLayout(self.strips)
        mixer.setContentsMargins(0, 0, 0, 0)
        self.controls = {}
        for column, label in enumerate(("通道", "静音", "独奏", "电平", "声像", "高通", "饱和")):
            mixer.addWidget(QLabel(label), 0, column)
        for i, t in enumerate(TRACKS, 1):
            mixer.addWidget(QLabel(TRACK_LABELS[t]), i, 0)
            controls = {}
            for col, key, label in [(1, "mute", "静音"), (2, "solo", "独奏")]:
                ctl = QCheckBox()
                ctl.setStyleSheet(
                    "QCheckBox::indicator{width:16px;height:16px;border:1px solid #646779;border-radius:3px;background:#191b23;} QCheckBox::indicator:checked{background:#aa8deb;border-color:#ded2ff;}"
                )
                ctl.setAccessibleName(TRACK_LABELS[t] + label)
                ctl.toggled.connect(lambda val, t=t, key=key: self._param(t, key, val))
                mixer.addWidget(ctl, i, col)
                controls[key] = ctl
            for col, key, lo, hi, step, suffix in (
                (3, "gain", -60.0, 12.0, 0.5, " dB"),
                (4, "pan", -1.0, 1.0, 0.05, ""),
                (5, "highpass", 0, 500, 10, " Hz"),
                (6, "drive", 0.0, 4.0, 0.1, " ×"),
            ):
                ctl = self._spin(lo, hi, step, suffix)
                ctl.setAccessibleName(TRACK_LABELS[t] + ("声像" if key == "pan" else key))
                ctl.valueChanged.connect(lambda val, t=t, key=key: self._param(t, key, val))
                mixer.addWidget(ctl, i, col)
                controls[key] = ctl
            self.controls[t] = controls
        root.addWidget(self.strips)
        aux = QHBoxLayout()
        aux.addWidget(QLabel("主总线"))
        self.master = self._spin(-60, 12, 0.5, " dB")
        self.master.valueChanged.connect(lambda v: self._param(None, "master_db", v))
        aux.addWidget(self.master)
        self.meter = QLabel("峰值   —  dBFS")
        self.meter.setMinimumWidth(130)
        aux.addWidget(self.meter)
        self.headroom = QLabel()
        self.headroom.setToolTip("主总线全曲采样峰值，以及超限保护产生的整体增益衰减")
        aux.addWidget(self.headroom)
        aux.addStretch()
        self.export_button = self._button(aux, "导出轨道 WAV…", self._export)
        root.addLayout(aux)
        transport = QHBoxLayout()
        self.play_button = self._button(transport, "播放", self._play)
        self._button(transport, "停止", self._rewind)
        self.loop = QCheckBox("循环")
        transport.addWidget(self.loop)
        self.mono = QCheckBox("单声道监听")
        self.mono.toggled.connect(self._switch_monitor)
        transport.addWidget(self.mono)
        self.clock = QLabel("00:00.00")
        self.clock.setStyleSheet("color: #c4b0ff; font: bold 17px 'Consolas';")
        transport.addWidget(self.clock)
        transport.addStretch()
        self.cancel_button = self._button(transport, "取消任务", self._cancel)
        self.apply_button = self._button(transport, "应用混音", self.accept)
        self._button(transport, "关闭", self.reject)
        root.addLayout(transport)
        self.status = QLabel()
        root.addWidget(self.status)
        self.shortcuts = []
        for key, func in (
            ("Space", self._play),
            ("Delete", lambda: self._edit("删除")),
            ("Ctrl+X", lambda: self._edit("剪切")),
            ("Ctrl+C", lambda: self._edit("复制")),
            ("Ctrl+V", lambda: self._edit("粘贴")),
            ("S", lambda: self._edit("分割")),
            ("Ctrl+Z", lambda: self._undo(False)),
            ("Ctrl+Y", lambda: self._undo(True)),
            ("R", self._set_region),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(func)
            self.shortcuts.append(shortcut)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)
        self._refresh()
        if missing:
            self._loaded = False
            self._refresh()
            QTimer.singleShot(0, lambda: self._restore(copy.deepcopy(state), tracks))
        elif self.session.frames:
            self.mix_timer.start(0)

    @property
    def state(self):
        return self.session.saved_state()

    def render_mix(self, cancel=None):
        if cancel is not None and cancel.is_set():
            raise InterruptedError("已取消")
        return self.cache if self.cache is not None else self.session.render(cancel)

    @staticmethod
    def _button(layout, label, callback, tip=""):
        b = QPushButton(label)
        b.setAutoDefault(False)
        b.clicked.connect(lambda: callback())
        if tip:
            b.setToolTip(tip)
        layout.addWidget(b)
        return b

    @staticmethod
    def _spin(lo, hi, step, suffix):
        ctl = QDoubleSpinBox()
        ctl.setRange(lo, hi)
        ctl.setDecimals(0 if step >= 1 else (1 if step >= 0.1 else 2))
        ctl.setSingleStep(step)
        ctl.setSuffix(suffix)
        ctl.setKeyboardTracking(False)
        return ctl

    def _restore(self, state, tracks):
        try:
            for key, name in state["external_sources"].items():
                if key in tracks or Path(name).is_file():
                    continue
                path, _ = QFileDialog.getOpenFileName(self, f"重新定位 {Path(name).name}")
                if not path:
                    self.status.setText(f"缺少素材 {name}。请关闭并重新定位。")
                    return
                state["external_sources"][key] = path
            self._job(
                "正在恢复轨道素材",
                lambda: Session(load_sources(state, tracks, self.cancel_job), self.sr, state),
                self._restored,
            )
        except Exception as exc:
            self._error(exc)

    def _restored(self, session):
        self.session = self.wave.session = session
        self._loaded = True
        self._changed("已恢复轨道与自动化")

    def _job(self, label, run, complete):
        if self.future is not None:
            return
        self._stop()
        self._cancel_monitor()
        self.cancel_job.clear()
        self.after_job = complete
        self.future = self.executor.submit(run)
        self.status.setText(label)
        self._refresh()

    def _cancel_monitor(self):
        self.mix_timer.stop()
        self.monitor_cancel.set()
        if self.monitor_future is not None:
            self.monitor_future.cancel()
            self.monitor_future = None

    def _cancel(self):
        if self.future is not None:
            self.cancel_job.set()
        else:
            self._cancel_monitor()
            self._waiting_play = False
            self._stop()
            self.status.setText("已取消主总线渲染，播放时可重试")
            self._refresh()

    def _queue_mix(self):
        if self.future is not None or not self._loaded or not self.session.frames or self.closing:
            return
        self._cancel_monitor()
        cancel = self.monitor_cancel = threading.Event()
        snapshot = Session(self.session.sources, self.sr, self.session.saved_state())
        cached, measurements = self.cache, self._mix_metrics
        mono = self.mono.isChecked()

        def run():
            metrics = measurements if cached is not None else {}
            mix = cached if cached is not None else snapshot.render(cancel, metrics=metrics)
            listen = mix
            if mono:
                folded = np.empty(len(mix), dtype=np.float32)
                for start in range(0, len(mix), 65536):
                    if cancel.is_set():
                        raise InterruptedError()
                    chunk = mix[start : start + 65536]
                    np.add(chunk[:, 0], chunk[:, 1], out=folded[start : start + len(chunk)])
                folded *= 0.5
                listen = np.broadcast_to(folded[:, None], mix.shape)
            return mix, metrics, listen

        self.monitor_future = self.executor.submit(run)
        self.cancel_button.setVisible(True)

    def _receive_mix(self):
        future = self.monitor_future
        if future is None or not future.done():
            return
        self.monitor_future = None
        self._refresh()
        try:
            mix, metrics, listen = future.result()
            self.cache = mix
            self.listen_mix = listen
            self._mix_metrics = metrics
            self.wave.set_master(mix)
            reduction = metrics["reduction_db"]
            self.headroom.setStyleSheet("color:#edb56d" if reduction > 0.01 else "color:#a5c4b7")
            if reduction > 0.01:
                self.headroom.setText(
                    f"峰值 {metrics['pre_peak_db']:+.1f} dBFS  ·  已衰减 {reduction:.1f} dB"
                )
            else:
                self.headroom.setText(f"全曲峰值 {metrics['peak_db']:.1f} dBFS")
            if self._active_preview and self.player.playing:
                if self.player.replace_buffer(listen):
                    self._heard_mix = listen
                    self.status.setText("正在试听更新后的混音")
                else:
                    self._stop()
            elif self._waiting_play:
                self._start(listen)
            else:
                self.status.setText("主总线已更新")
        except Exception as error:
            self.status.setText(f"主总线渲染或试听失败 · {error}")
        self._waiting_play = False

    def _tick(self):
        device_message = self.player.poll_device() if self._active_preview else ""
        self._receive_mix()
        if self.future is not None and self.future.done():
            job, complete = self.future, self.after_job
            self.future = self.after_job = None
            self._refresh()
            if self.closing:
                self.reject()
                return
            try:
                result = job.result()
                if self.cancel_job.is_set():
                    raise InterruptedError()
                complete(result)
            except InterruptedError:
                self.status.setText("已取消任务")
            except Exception as exc:
                self._error(exc)
            if self.cache is None and self._loaded and self.monitor_future is None:
                self.mix_timer.start(120)
        if self._active_preview:
            self.wave.cursor = int(self.player.position * self.sr)
            if self.player.playing:
                self.clock.setText(clock_text(self.wave.cursor, self.sr))
                block = self._heard_mix[max(0, self.wave.cursor - self.sr // 20) : self.wave.cursor]
                if len(block):
                    amplitude = max(float(block.max()), -float(block.min()), 1e-6)
                    self.meter.setText(f"峰值   {20 * math.log10(amplitude):.1f} dBFS")
                self.wave.update()
            else:
                self._active_preview = False
                self._heard_mix = None
                self.player.pause()
                self.play_button.setText("播放")
                self.status.setText("试听结束")
                self.wave.update()
        if device_message:
            self.status.setText(device_message)

    def _error(self, error):
        self.status.setText(f"操作失败 · {error}")
        QMessageBox.warning(self, "多轨混音", str(error))

    def _refresh(self):
        self._refreshing = True
        try:
            ready = self._loaded and self.future is None
            self.balance_button.setEnabled(ready and self.session.frames > 0)
            self.rack_button.setEnabled(ready)
            self.mono.setEnabled(ready)
            self.tools.setEnabled(ready)
            self.wave.setEnabled(ready)
            self.strips.setEnabled(ready)
            self.master.setEnabled(ready)
            self.play_button.setEnabled(ready and self.session.frames > 0)
            self.export_button.setEnabled(ready and self.session.frames > 0)
            self.apply_button.setEnabled(ready and self.session.frames > 0)
            self.cancel_button.setVisible(
                self.future is not None or self.monitor_future is not None
            )
            self.undo_button.setEnabled(bool(self.session.undo_stack))
            self.redo_button.setEnabled(bool(self.session.redo_stack))
            for t, widgets in self.controls.items():
                for key, widget in widgets.items():
                    val = self.session.strip(t)[key]
                    if isinstance(widget, QCheckBox):
                        widget.setChecked(val)
                    else:
                        widget.setValue(val)
            self.master.setValue(self.session.state["master_db"])
            self._view()
            self._selection()
            self.wave.update()
        finally:
            self._refreshing = False

    def _selection(self):
        a, b = self.wave.first, self.wave.last
        if a < b:
            self.region.setText(
                f"选区   {clock_text(a, self.sr)}   –   {clock_text(b, self.sr)}     ·     {(b - a) / self.sr:.3f} 秒"
            )
        else:
            self.region.setText("拖动波形选择编辑或试听范围")
        self.clock.setText(clock_text(self.wave.cursor, self.sr))

    def _changed(self, msg, *, live=False):
        if not live:
            self._stop()
        self._cancel_monitor()
        self.cache = None
        self.listen_mix = None
        self._mix_metrics = None
        self.wave.set_master(None)
        self.headroom.clear()
        self.wave.cursor = min(self.wave.cursor, self.wave.total)
        self.wave.first = min(self.wave.first, self.wave.total)
        self.wave.last = min(self.wave.last, self.wave.total)
        self._refresh()
        self.status.setText(msg)
        self.mix_timer.start(140)

    def _view(self):
        self.wave.offset = min(self.wave.offset, self.wave.total - self.wave.span)
        self.scroll.blockSignals(True)
        self.scroll.setRange(0, min(10000, self.wave.total - self.wave.span))
        self.scroll.setEnabled(self.wave.zoom > 1.0)
        self.scroll.setPageStep(max(1, int(10000 / self.wave.zoom)))
        self.scroll.setValue(
            round(
                self.wave.offset / max(1, self.wave.total - self.wave.span) * self.scroll.maximum()
            )
        )
        self.scroll.blockSignals(False)

    def _scroll(self, value):
        self.wave.offset = int(
            value / max(1, self.scroll.maximum()) * (self.wave.total - self.wave.span)
        )
        self.wave.update()

    def _choose_lane(self, index):
        self.wave.lane = TRACKS[index]
        self.wave.update()

    def _set_wave_gain(self, value):
        self.wave.wave_gain = value
        self.wave.update()

    def _param(self, track, key, val):
        if not self._refreshing:
            self.session.set_param(track, key, val)
            self._changed("正在更新主总线", live=True)

    def _stop(self):
        if self._active_preview:
            self.wave.cursor = int(self.player.position * self.sr)
            self.player.stop()
        self._active_preview = False
        self._heard_mix = None
        self._waiting_play = False
        self.play_button.setText("播放")
        self.meter.setText("峰值   —  dBFS")

    def _rewind(self):
        self._stop()
        self.wave.cursor = self.wave.first if self.wave.last > self.wave.first else 0
        self._selection()
        self.wave.update()

    def _play(self):
        if self.future is not None or not self._loaded or not self.session.frames:
            return
        if self._active_preview:
            self._stop()
            self.play_button.setText("继续")
            self.status.setText("已暂停")
            return
        if self.listen_mix is None:
            self._waiting_play = True
            self.status.setText("正在准备试听缓冲")
            if self.monitor_future is None:
                self._queue_mix()
        else:
            try:
                self._start(self.listen_mix)
            except Exception as exc:
                self._error(exc)

    def _switch_monitor(self):
        self.listen_mix = None
        self._queue_mix()

    def _start(self, mix):
        a, b = self.wave.first, self.wave.last
        region = b > a
        if not region:
            a, b = 0, len(mix)
        pos = self.wave.cursor if a <= self.wave.cursor < b else a
        # Start from the selected boundary on every loop iteration.
        if self.loop.isChecked():
            pos = a
        self.player.play(
            mix,
            self.sr,
            start=pos / self.sr,
            end=min(b, len(mix)) / self.sr,
            loop=self.loop.isChecked(),
        )
        self._heard_mix = mix
        self._active_preview = True
        self.play_button.setText("暂停")
        self.status.setText("正在试听选区" if region else "正在试听主总线")
        if self.player.device_notice:
            self.status.setText(self.player.device_notice)

    def _undo(self, redo):
        if self.future is not None or not self._loaded:
            return
        self.session.undo(redo)
        self._changed("已重做" if redo else "已撤销")

    def _menu_at(self, point):
        menu = QMenu(self)
        menu.addAction("设置选区…\tR").triggered.connect(self._set_region)
        menu.addSeparator()
        for name, key in (
            ("剪切", "Ctrl+X"),
            ("复制", "Ctrl+C"),
            ("粘贴", "Ctrl+V"),
            ("删除", "Del"),
            ("分割", "S"),
            ("合并相邻片段", ""),
            ("淡入", ""),
            ("淡出", ""),
            ("包络点…", ""),
            ("移动选区至…", ""),
        ):
            act = menu.addAction(name + ("\t" + key if key else ""))
            act.triggered.connect(lambda checked=False, name=name: self._edit(name))
        with managed_dialog(menu):
            menu.exec(point)

    def _set_region(self):
        if self.future is not None or not self._loaded:
            return
        end = self.session.frames / self.sr
        start, ok = QInputDialog.getDouble(
            self, "设置选区", "起点（秒）", self.wave.first / self.sr, 0, end, 4
        )
        if not ok:
            return
        stop, ok = QInputDialog.getDouble(
            self,
            "设置选区",
            "终点（秒）",
            max(start, self.wave.last / self.sr),
            start,
            end,
            4,
        )
        if ok:
            self._stop()
            self.wave.first = self.wave.cursor = round(start * self.sr)
            self.wave.last = round(stop * self.sr)
            self._selection()
            self.wave.update()

    def _edit_menu(self):
        widget = self.tools.findChildren(QPushButton)[1]
        self._menu_at(widget.mapToGlobal(widget.rect().bottomLeft()))

    def _edit(self, name):
        if self.future is not None or not self._loaded:
            return
        t, a, b, frame = (
            self.wave.lane,
            self.wave.first,
            self.wave.last,
            self.wave.cursor,
        )
        if name in ("剪切", "复制", "删除", "淡入", "淡出", "移动选区至…") and a == b:
            self.status.setText("先在当前轨道拖动选择范围")
            return
        if name in ("剪切", "复制"):
            self.session.copy_region(t, a, b)
            if not self.session.clipboard:
                self.status.setText("选区没有音频")
                return
            if name == "复制":
                self.status.setText("已复制选区")
                return
        if name in ("删除", "剪切"):
            self.session.replace(t, a, b, [])
        elif name == "粘贴":
            if not self.session.clipboard:
                self.status.setText("剪贴板为空")
                return
            self.session.paste(t, frame)
        elif name == "分割":
            if not self.session.split(t, frame):
                self.status.setText("将光标置于片段内部")
                return
        elif name == "合并相邻片段":
            if not self.session.join(t, frame):
                self.status.setText("请选择来自同一素材且首尾连续的相邻片段")
                return
        elif name in ("淡入", "淡出"):
            self.session.fade(t, a, b, name == "淡入")
        elif name == "包络点…":
            db, ok = QInputDialog.getDouble(self, "音量包络", "光标处的电平 (dB)", 0, -60, 12, 1)
            if not ok:
                return
            if not self.session.point(t, frame, 10 ** (db / 20)):
                self.status.setText("先将光标置于音频片段内")
                return
        elif name == "移动选区至…":
            dest, ok = QInputDialog.getDouble(
                self,
                "移动选区",
                "新的起始时间（秒）",
                a / self.sr,
                0,
                self.wave.total / self.sr,
                4,
            )
            if not ok:
                return
            pieces = self.session.select(t, a, b)
            if not pieces:
                self.status.setText("选区没有音频")
                return
            start = int(round(dest * self.sr))
            self.session.move(t, a, b, start)
            self.wave.cursor = self.wave.first = start
            self.wave.last = start + b - a
        self._changed("已" + name.rstrip("…"))

    def _import(self):
        from .audioio import decode

        file, _ = QFileDialog.getOpenFileName(
            self,
            "添加到当前轨道",
            "",
            "音频 (*.wav *.mp3 *.m4a *.flac *.ogg *.aac *.aiff *.aif);;所有文件 (*)",
        )
        if file:
            track, frame = self.wave.lane, self.wave.cursor

            def finish(result):
                data, _ = result
                self.session.import_clip(track, uuid.uuid4().hex, file, data, frame)
                self._changed(f"已添加 {Path(file).name}")

            self._job("正在解码轨道素材", lambda: decode(file, cancel=self.cancel_job), finish)

    def _export(self):
        from .audioio import encode

        t = self.wave.lane
        if not self.session.strip(t)["clips"]:
            self.status.setText("当前轨道没有音频")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出独立轨道（保留时间对齐）", t + ".wav", "WAV 24-bit (*.wav)"
        )
        if not path:
            return
        if Path(path).exists():
            self._error("请选择新的文件名，以保留原始录音与已有文件")
            return

        def run():
            data = self.session.render(self.cancel_job, track=t)
            encode(path, data, self.sr, bitdepth=24, cancel=self.cancel_job)

        self._job("正在导出独立轨道", run, lambda _: self.status.setText(f"已导出 {path}"))

    def _balance(self):
        from .studio_balance import measure
        from .studio_mix_dialogs import BalanceDialog

        def ready(report):
            with managed_dialog(BalanceDialog(self.session, report, self)) as dialog:
                if dialog.exec():
                    self._changed("已应用混音设置")

        self._job(
            "正在测量多轨响度、相位和频谱重叠",
            lambda: measure(self.session, self.cancel_job, self.cache),
            ready,
        )

    def _rack(self):
        from .studio_mix_dialogs import RackDialog

        with managed_dialog(RackDialog(self.session, self.wave.lane, self)) as dialog:
            if dialog.exec():
                self._changed("已更新效果器链", live=True)

    def done(self, result):
        self._cancel_monitor()
        if self.future is not None:
            self.closing = True
            self.cancel_job.set()
            self.status.setText("正在停止任务")
            return
        self._stop()
        self.timer.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
        super().done(result)
