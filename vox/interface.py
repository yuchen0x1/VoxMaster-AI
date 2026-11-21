import copy
import datetime
import uuid
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from . import audioio, engine, hardware, service
from .acoustics import compare_lines, report_lines
from .playback import Playback
from .storage import (
    ROOT,
    PROJECT_EXT,
    load_project,
    preferences,
    project,
    read_json,
    save_project,
    write_json,
)
from .dialogs import choices, label, ParameterDialog, ExportDialog, managed_dialog
from .jobs import PublishedFile, Worker
from .service import prepare, tuning_plan, SR
from .reference import comparison, describe_match, space_notes
from .review import ReportDialog, PreviewDialog
from .song import TARGETS, MASTERING
from .song_dialog import SongDialog
from .visual import (Timeline, Spectrum, timecode, app_icon, ElidedLabel, WrappedLabel,
                     TransportShortcutGuard)
from .theme import manager as theme_manager

FORMATS = "音频 (*.wav *.mp3 *.flac *.m4a *.aac *.ogg *.aiff *.aif);;所有文件 (*)"
KINDS = [
    "自动判断",
    "普通语音喊麦",
    "旋律型喊麦",
    "Rap",
    "普通演唱",
    "高强度喊唱",
    "混合人声",
    "人声加伴奏",
    "纯伴奏",
    "未知类型",
]
LEGACY_KINDS = {
    "语音喊麦": "普通语音喊麦",
    "旋律喊麦": "旋律型喊麦",
    "混合音频": "人声加伴奏",
    "其他": "未知类型",
}
MODES = {
    "vocal": ("独立人声", "AI 一键调音", "导入独立人声录音，分析并调音。"),
    "song": ("整曲处理", "整曲处理…", "导入带伴奏的整首歌曲，分轨、混音并处理母带。"),
    "multitrack": ("多轨混音", "打开多轨工作室", "导入音频后，打开工作室手动分配轨道和编辑。"),
}
STEM_ROLES = ("Vocal", "Instrumental")


def button(caption, fn, role=None):
    b = QPushButton(caption)
    b.clicked.connect(lambda: fn())
    if role:
        b.setObjectName(role)
    return b


def splitline(layout):
    line = QFrame()
    line.setObjectName("rule")
    layout.addWidget(line)


def clockstr():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VoxMaster AI · 人声调音工作站")
        self.setMinimumSize(820, 560)
        available = self.screen().availableGeometry()
        self.resize(min(1280, available.width()), min(790, available.height() - 40))
        self.setAcceptDrops(True)
        self.settings = preferences()
        try:
            audioio.set_cache_directory(self.settings.get("cache_dir"))
        except OSError:
            audioio.set_cache_directory(None)
        self.s = None
        self.import_mode = "vocal"
        self.path = None
        self.worker = None
        self.player = Playback()
        self.cursor = 0.0
        self.listening = False
        self.monitor_volume = 0.75
        self.undo_stack = []
        self.redo_stack = []
        self.last_autosave = None
        self.custom = self.settings.get("presets", {})
        self.device_report = {}
        self.build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(60)
        self.install_actions()
        self.refresh()
        QTimer.singleShot(0, self.detect)

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.setContentsMargins(18, 10, 16, 10)
        mark = QLabel()
        mark.setPixmap(app_icon().pixmap(34, 34))
        top.addWidget(mark)
        top.addSpacing(4)
        top.addWidget(label("VoxMaster AI", "brand"))
        top.addSpacing(16)
        self.project_name = ElidedLabel("未命名工程", "sub")
        self.project_name.setAccessibleName("当前工程名称")
        top.addWidget(self.project_name, 1)
        top.addWidget(button("打开工程", self.open_project))
        top.addWidget(button("保存工程", self.save))
        self.export_btn = button("导出成品", self.export)
        top.addWidget(self.export_btn)
        layout.addLayout(top)
        splitline(layout)
        modes = QHBoxLayout()
        modes.setContentsMargins(18, 6, 16, 6)
        modes.addWidget(label("工作模式", "section"))
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for mode, (caption, _, hint) in MODES.items():
            choice = button(caption, lambda mode=mode: self.select_mode(mode), "mode_" + mode)
            choice.setCheckable(True)
            choice.setToolTip(hint)
            self.mode_group.addButton(choice)
            self.mode_buttons[mode] = choice
            modes.addWidget(choice)
        self.mode_hint = label("", "sub")
        self.mode_hint.setWordWrap(True)
        modes.addWidget(self.mode_hint, 1)
        layout.addLayout(modes)
        splitline(layout)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        layout.addLayout(body, 1)
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(151)
        side_shell = QVBoxLayout(side)
        side_shell.setContentsMargins(0, 0, 0, 0)
        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side_scroll.setAccessibleName("工作站导航")
        nav_content = QWidget()
        nav_content.setObjectName("sideContent")
        nav = QVBoxLayout(nav_content)
        nav.setContentsMargins(10, 14, 10, 12)
        nav.setSpacing(3)
        for caption, fn in [
            ("工作台", self.home),
            ("我的项目", self.projects),
            ("AI 一键调音", self.tune),
            ("专业混音", self.studio),
            ("参考匹配", self.reference),
            ("人声分离", self.separate),
            ("智能尾音", lambda: self.parameters(2)),
            ("预设库", self.library),
            ("AI 模型中心", self.models),
            ("导出中心", self.export),
        ]:
            b = button(caption, fn, "nav")
            if caption == "工作台":
                b.setCheckable(True)
                b.setChecked(True)
            nav.addWidget(b)
        nav.addStretch()
        splitline(nav)
        nav.addWidget(button("设备与设置", self.settings_view, "nav"))
        side_scroll.setWidget(nav_content)
        side_shell.addWidget(side_scroll)
        body.addWidget(side)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        body.addWidget(splitter, 1)
        center = QWidget()
        c = QVBoxLayout(center)
        c.setContentsMargins(18, 17, 18, 12)
        c.setSpacing(9)
        title = QHBoxLayout()
        self.track_name = ElidedLabel("人声工作台", "title")
        self.track_name.setAccessibleName("当前工作区")
        title.addWidget(self.track_name, 1)
        self.import_btn = button("＋  导入音频", self.import_audio)
        title.addWidget(self.import_btn)
        c.addLayout(title)
        self.meta = label("选择一段录音，开始本地分析。", "sub")
        self.meta.setWordWrap(True)
        c.addWidget(self.meta)
        c.addSpacing(4)
        line = QHBoxLayout()
        line.addWidget(label("音频时间轴", "section"))
        line.addStretch()
        self.matched = QCheckBox("等响试听")
        self.matched.setToolTip("按综合响度衰减较响的一侧，方便判断音色。仅作用于监听。")
        self.matched.toggled.connect(self.set_monitor_gain)
        line.addWidget(self.matched)
        self.a = button("A   原音", lambda: self.switch(False))
        self.b = button("B   成品", lambda: self.switch(True))
        for b in (self.a, self.b):
            b.setCheckable(True)
            line.addWidget(b)
        c.addLayout(line)
        self.timeline = Timeline()
        self.timeline.seek.connect(self.seek)
        self.timeline.selected.connect(self.region_selected)
        self.timeline.import_requested.connect(self.import_audio)
        self.timeline.setContextMenuPolicy(Qt.CustomContextMenu)
        self.timeline.customContextMenuRequested.connect(self.wave_menu)
        c.addWidget(self.timeline, 4)
        c.addWidget(label("监听频谱", "section"))
        self.spectrum = Spectrum()
        c.addWidget(self.spectrum, 1)
        splitline(c)
        line = QHBoxLayout()
        self.style = choices(list(engine.PRESETS) + list(self.custom))
        self.style.setAccessibleName("人声调音风格")
        self.style_label = label("喊麦风格")
        self.style_label.setBuddy(self.style)
        line.addWidget(self.style_label)
        line.addWidget(self.style, 1)
        self.go = button("AI 一键调音", self.run_mode, "primary")
        line.addWidget(self.go)
        c.addLayout(line)
        self.progress_text = label("等待导入", "sub")
        self.progress_text.setWordWrap(True)
        jb = QHBoxLayout()
        jb.addWidget(self.progress_text, 1)
        self.cancel_btn = button("取消任务", self.cancel)
        jb.addWidget(self.cancel_btn)
        c.addLayout(jb)
        self.progress = QProgressBar()
        self.progress.setAccessibleName("音频处理进度")
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        c.addWidget(self.progress)
        center_scroll = QScrollArea()
        center_scroll.setWidgetResizable(True)
        center_scroll.setFrameShape(QFrame.NoFrame)
        center_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        center_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        center_scroll.setAccessibleName("工作台内容")
        center_scroll.setWidget(center)
        splitter.addWidget(center_scroll)
        right = QFrame()
        right.setObjectName("inspector")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(14, 17, 14, 12)
        rl.addWidget(label("调音检查器", "section"))
        splitline(rl)
        scroll = QScrollArea()
        scroll.setObjectName("inspectorScroll")
        scroll.setWidgetResizable(True)
        panel = QWidget()
        panel.setObjectName("inspectorContent")
        r = QVBoxLayout(panel)
        r.setSizeConstraint(QLayout.SetMinAndMaxSize)
        r.setContentsMargins(0, 3, 2, 4)
        r.setSpacing(9)
        self.report_mode = label("原音测量", "sub")
        r.addWidget(self.report_mode)
        self.level = label("—   LUFS", "value")
        self.peak = label("—   dBTP", "value")
        r.addWidget(self.level)
        r.addWidget(self.peak)
        splitline(r)
        r.addWidget(label("音频体检", "section"))
        self.issues = WrappedLabel("导入后查看声学测量结果。", "sub")
        self.issues.setWordWrap(True)
        self.issues.setTextInteractionFlags(Qt.TextSelectableByMouse)
        r.addWidget(self.issues)
        self.full = button("完整分析报告", self.report_view)
        r.addWidget(self.full)
        splitline(r)
        r.addWidget(label("处理方案", "section"))
        self.kind = choices(KINDS)
        self.kind.setAccessibleName("音频内容类型")
        r.addWidget(self.kind)
        self.advanced = button("调整效果器与链路", self.parameters)
        r.addWidget(self.advanced)
        self.plan_label = WrappedLabel("", "sub")
        self.plan_label.setWordWrap(True)
        r.addWidget(self.plan_label)
        self.match_label = WrappedLabel("尚未载入参考音频", "sub")
        self.match_label.setWordWrap(True)
        r.addWidget(self.match_label)
        for wrapped in (self.issues, self.plan_label, self.match_label):
            policy = wrapped.sizePolicy()
            policy.setVerticalPolicy(QSizePolicy.Minimum)
            wrapped.setSizePolicy(policy)
        r.addStretch()
        scroll.setWidget(panel)
        rl.addWidget(scroll, 1)
        splitter.addWidget(right)
        splitter.setSizes([770, 255])
        splitter.setStretchFactor(0, 1)
        splitline(layout)
        transport = QVBoxLayout()
        transport.setContentsMargins(15, 7, 15, 7)
        playback_row = QHBoxLayout()
        self.play_btn = button("▶  播放", self.play)
        self.stop_btn = button("■", self.stop)
        self.stop_btn.setAccessibleName("停止播放并回到开头")
        self.stop_btn.setToolTip("停止并回到开头")
        self.loop = QCheckBox("循环")
        playback_row.addWidget(self.play_btn)
        playback_row.addWidget(self.stop_btn)
        playback_row.addWidget(self.loop)
        self.clock = label("00:00.00", "clock")
        self.clock.setAccessibleName("播放位置")
        playback_row.addSpacing(10)
        playback_row.addWidget(self.clock)
        self.total = label("/ 00:00.00", "sub")
        self.total.setAccessibleName("音频总时长")
        playback_row.addWidget(self.total)
        playback_row.addStretch()
        self.device_button = button("音频设备", self.settings_view)
        self.device_button.setMaximumWidth(160)
        playback_row.addWidget(self.device_button)
        transport.addLayout(playback_row)
        monitor_row = QHBoxLayout()
        self.meter = label("— dBFS", "sub")
        self.meter.setAccessibleName("实时输出电平")
        monitor_row.addWidget(self.meter)
        monitor_row.addStretch()
        volume_label = label("监听音量", "sub")
        vol = QSlider(Qt.Horizontal)
        vol.setAccessibleName("监听音量")
        vol.setAccessibleDescription("调整本机试听音量，不改变导出成品电平。")
        volume_label.setBuddy(vol)
        monitor_row.addWidget(volume_label)
        vol.setRange(0, 100)
        vol.setValue(75)
        self.player.volume = 0.75
        vol.valueChanged.connect(self.set_monitor_volume)
        vol.setFixedWidth(85)
        monitor_row.addWidget(vol)
        transport.addLayout(monitor_row)
        layout.addLayout(transport)

    def install_actions(self):
        for key, fn in [
            ("Ctrl+O", self.import_audio),
            ("Ctrl+Shift+O", self.open_project),
            ("Ctrl+S", self.save),
            ("Ctrl+Shift+S", lambda: self.save(True)),
            ("Space", self.play),
            ("Ctrl+Z", lambda: self.travel(False)),
            ("Ctrl+Y", lambda: self.travel(True)),
            ("Ctrl+E", self.export),
            ("Ctrl+Return", self.run_mode),
        ]:
            action = QAction(self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(lambda _=False, fn=fn: fn())
            self.addAction(action)
            if key == "Space":
                self.transport_guard = TransportShortcutGuard(self, action)

    def notice(self, msg):
        QMessageBox.information(self, "VoxMaster AI", str(msg))

    def available(self, source=True):
        if self.worker is not None:
            self.progress_text.setText("请等待当前任务完成，或先取消任务。")
            return False
        if source and self.s is None:
            self.import_audio()
            return False
        return True

    def run_job(self, text, work, success):
        if self.worker:
            return
        job = Worker(work, self)
        self.worker = job
        self.progress.setRange(0, 0)
        self.progress_text.setText(text)
        self.refresh_controls()
        job.progress.connect(self.on_progress)
        job.succeeded.connect(lambda result: self.job_success(success, result))
        job.failed.connect(self.failed)
        job.cancelled.connect(lambda: self.progress_text.setText("任务已取消"))
        job.finished.connect(self.job_finished)
        job.start()

    def job_success(self, cb, result):
        if self.worker and self.worker.cancel.is_set() and not getattr(result, "publication_committed", False):
            self.progress_text.setText("任务已取消，保留上一版本")
            return
        try:
            self.progress_text.setText("任务完成")
            cb(result)
        except Exception as exc:
            self.failed(str(exc))

    def job_finished(self):
        job = self.worker
        self.worker = None
        if job:
            job.deleteLater()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.refresh_controls()

    def on_progress(self, f, text):
        self.progress_text.setText(text)
        if f >= 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(round(f * 100))
        else:
            self.progress.setRange(0, 0)

    def failed(self, msg):
        self.progress_text.setText("任务未完成")
        self.notice(msg)

    def cancel(self):
        if self.worker:
            self.worker.cancel.set()
            self.progress_text.setText("正在取消…")

    def save_settings(self):
        write_json(ROOT / "settings.json", self.settings)

    def detect(self):
        self.hardware_job = Worker(lambda cancel, progress: hardware.report(), self)
        self.hardware_job.succeeded.connect(self.hardware_ready)
        self.hardware_job.failed.connect(lambda m: setattr(self, "device_report", {"检测提示": m}))
        self.hardware_job.start()

    def hardware_ready(self, report):
        self.device_report = report
        try:
            write_json(ROOT / "hardware.json", report)
            self.player.device = hardware.resolve_output(self.settings, report)
            self.show_device_names()
            if not self.settings.get("hardware_seen"):
                self.progress_text.setText("已生成首次设备报告，可在「设备与设置」查看。")
                self.settings["hardware_seen"] = True
                self.save_settings()
        except Exception as exc:
            self.progress_text.setText(str(exc))

    def show_device_names(self):
        inventory = self.device_report
        devices = {item["id"]: item["name"] for item in inventory.get("devices", [])}
        selected = self.player.device
        output = devices.get(
            inventory.get("default_output") if selected is None else selected, "系统默认"
        )
        input_name = devices.get(inventory.get("default_input"), "无")
        self.device_button.setText("输出 · " + (output if len(output) <= 11 else output[:10] + "…"))
        self.device_button.setToolTip(f"输入  {input_name}\n输出  {output}\n点击设置监听设备")

    def audio(self):
        if self.s is None:
            return None
        return self.s.output if self.listening and self.s.output is not None else self.s.original

    def mode(self):
        if self.s is None:
            return self.import_mode
        doc = self.s.document
        return doc.get("mode", "multitrack" if doc.get("studio") else "vocal")

    def select_mode(self, mode):
        current = self.mode()
        self.mode_buttons[current].setChecked(True)
        if mode == current or not self.available(False):
            return
        if self.s is None:
            self.import_mode = mode
            self.refresh()
            self.progress_text.setText("等待导入 · " + MODES[mode][0])
            return
        # This is a routing choice, not a request to replace the current render.
        doc = copy.deepcopy(self.s.document)
        doc["mode"] = mode
        self.rebuild(doc, "切换工作模式 · " + MODES[mode][0])

    def run_mode(self):
        {"vocal": self.tune, "song": self.song_mix, "multitrack": self.studio}[self.mode()]()

    def refresh_controls(self):
        has = self.s is not None
        wet = has and self.s.output is not None
        free = self.worker is None
        mode = self.mode()
        _, primary, hint = MODES[mode]
        if has:
            if mode == "song":
                if self.s.document.get("song"):
                    primary, hint = "复核整曲方案…", "方案已生成，可复核参数或切换 A/B 等响试听。"
                elif self.has_song_stems():
                    hint = "人声与伴奏分轨已就绪，可分析并生成整曲方案。"
                else:
                    hint = "已导入歌曲，下一步确认本地分轨及整曲处理。"
            elif mode == "multitrack":
                hint = "在工作室手动管理轨道与剪辑；立体声不代表素材角色。"
            else:
                hint = "选择喊麦风格，按录音测量值调音。"
            if mode != "song" and self.s.document.get("song"):
                hint += " 已应用的整曲方案仍保留。"
        else:
            hint = "选择模式后" + hint
        self.mode_hint.setText(hint)
        self.mode_buttons[mode].setChecked(True)
        for choice in self.mode_buttons.values():
            choice.setEnabled(free)
        self.go.setText(primary)
        self.style_label.setVisible(mode == "vocal")
        self.style.setVisible(mode == "vocal")
        self.kind.setVisible(mode == "vocal")
        self.a.setEnabled(has)
        self.matched.setEnabled(wet)
        self.b.setEnabled(wet)
        self.a.setChecked(has and not self.listening)
        self.b.setChecked(self.listening and wet)
        for b in (self.go, self.advanced):
            b.setEnabled(has and free)
        self.import_btn.setEnabled(free)
        self.play_btn.setEnabled(has)
        self.stop_btn.setEnabled(has)
        self.export_btn.setEnabled(wet and free)
        self.full.setEnabled(has)
        self.cancel_btn.setVisible(not free)

    def refresh(self):
        self.refresh_controls()
        s = self.s
        if not s:
            self.timeline.set_data(None, None, 0)
            self.track_name.setText("人声工作台")
            self.project_name.setText("未命名工程")
            self.track_name.setToolTip("")
            self.meta.setText("导入后在本机进行音频体检。")
            self.level.setText("—   LUFS")
            self.peak.setText("—   dBTP")
            self.issues.setText("导入后查看声学测量结果。")
            self.plan_label.clear()
            self.match_label.setText("尚未载入参考音频")
            return
        self.track_name.setText(Path(s.document["source"]).stem)
        self.track_name.setToolTip(s.document["source"])
        self.project_name.setText(Path(self.path).stem if self.path else "未保存工程")
        bits = s.metadata.get("bit_depth")
        depth = f"{bits} bit" if bits else "编码音频"
        self.meta.setText(
            f"{s.metadata.get('sample_rate', '—')} Hz    /    {s.metadata.get('channels', '—')} 声道    /    {depth}    /    {timecode(len(s.original) / SR)}"
        )
        r = s.measured if self.listening and s.measured else s.analysis
        self.level.setText(f"{r['lufs']:.1f}  LUFS")
        self.peak.setText(f"{r['true_peak_db']:.1f}  dBTP")
        self.report_mode.setText("成品测量" if self.listening else "原音测量")
        self.issues.setText(
            "\n\n".join(str(x) for x in r.get("diagnostics", [])[:4]) or "未检出显著异常。"
        )
        self.match_label.setText(
            "参考 · " + Path(s.document["reference"]).name
            if s.document.get("reference")
            else "尚未载入参考音频"
        )
        doc = s.document
        p = doc.get("params")
        song = doc.get("song")
        if song:
            self.plan_label.setText(
                f"整曲 · {TARGETS[song['target']]} / {MASTERING[song['master']]}\n"
                f"人声 {song['vocal_gain_db']:+.2f} dB，伴奏 {song['instrumental_gain_db']:+.2f} dB。\n"
                f"总线母带目标 {song['target_lufs']:.2f} LUFS，最高 {song['ceiling_db']:.2f} dBTP。"
            )
        elif p:
            self.plan_label.setText(
                f"高通 {p['highpass_hz']:.0f} Hz，低中频 {p['mud_db']:+.1f} dB，"
                f"压缩 {p['ratio']:.1f}:1，目标 {p['target_lufs']:.1f} LUFS。"
            )
        else:
            self.plan_label.setText(MODES[self.mode()][2])
        warnings = self.render_warnings(s)
        if warnings:
            self.plan_label.setText(self.plan_label.text() + "\n\n复测提示\n" + "\n".join(warnings))
        lengths = (len(s.original) / SR, len(s.output) / SR if s.output is not None else 0.0)
        self.timeline.set_data(s.original_wave, s.output_wave, max(lengths), lengths)
        self.set_monitor_gain()
        self.total.setText("/ " + timecode(len(self.audio()) / SR))

    def home(self):
        self.timeline.setFocus()

    def recent_paths(self):
        recent = self.settings.get("recent", [])
        if not isinstance(recent, list):
            return []
        return [p for p in recent if isinstance(p, str) and p]

    def remember(self, path):
        self.settings["recent"] = [str(path)] + [
            p for p in self.recent_paths() if p != str(path)
        ][:15]
        try:
            self.save_settings()
        except Exception as exc:
            # Preferences are ancillary to an already committed project/checkpoint.
            return "最近工程记录未保存：" + str(exc)
        return None

    def autosave(self):
        if not self.s:
            return
        path = ROOT / "recovery" / (self.recovery_id + PROJECT_EXT)
        save_project(path, self.s.document, False)
        self.last_autosave = path

    def commit(self, session, *, path=None, reset=False, record=True):
        # prepare() runs on a worker; media may change while its result waits in the GUI queue.
        # Revalidate before writing the recovery checkpoint or mutating any live state.
        service.verify_session_media(session)
        recovery_id = uuid.uuid4().hex if reset else getattr(self, "recovery_id", uuid.uuid4().hex)
        checkpoint = ROOT / "recovery" / (recovery_id + PROJECT_EXT)
        # Write the recovery checkpoint before changing live audio or undo history.
        save_project(checkpoint, session.document, False)
        self.stop()
        if reset:
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.path = path
        self.recovery_id = recovery_id
        if not reset and self.s and record:
            self.undo_stack.append(copy.deepcopy(self.s.document))
            self.undo_stack = self.undo_stack[-30:]
            self.redo_stack.clear()
        self.s = session
        self.style.setCurrentText(session.document["style"])
        kind = session.document.get("kind", KINDS[0])
        self.kind.setCurrentText(LEGACY_KINDS.get(kind, kind))
        self.listening = session.output is not None
        self.timeline.region = None
        self.refresh()
        self.last_autosave = checkpoint
        if reset and path:
            return self.remember(path)
        return None

    @staticmethod
    def render_warnings(session):
        evidence = (session.document.get("separation") or {}).get("reconstruction", {})
        return list(dict.fromkeys([
            *session.audit.get("warnings", ()), *session.audit.get("output_warnings", ()),
            *evidence.get("warnings", ()),
        ]))

    def show_ready(self, session):
        warnings = self.render_warnings(session)
        if warnings:
            self.progress_text.setText("处理完成。复测提示 · " + warnings[0])
        elif session.output is not None:
            self.progress_text.setText("成品已就绪，可 A/B 等响试听并导出。")
        else:
            self.progress_text.setText({
                "vocal": "音频体检完成，可开始一键调音。",
                "song": "音频体检完成，可进入整曲处理。",
                "multitrack": "音频体检完成，可打开多轨工作室。",
            }[self.mode()])

    def rebuild(self, doc, msg, *, reset=False, path=None, done=None):
        previous = None if reset else self.s

        def success(session):
            warning = self.commit(session, path=path, reset=reset, record=done is None)
            if done:
                done()
            self.show_ready(session)
            if warning:
                self.progress_text.setText(self.progress_text.text() + " · " + warning)

        self.run_job(msg, lambda ev, pg: prepare(doc, ev, pg, previous), success)

    def import_audio(self):
        if not self.available(False):
            return
        mode_label = MODES[self.mode()][0]
        p, _ = QFileDialog.getOpenFileName(
            self, "导入音频 · " + mode_label, self.settings.get("import_dir", ""), FORMATS
        )
        if p:
            self.open_path(p)

    def open_project(self):
        if not self.available(False):
            return
        p, _ = QFileDialog.getOpenFileName(
            self, "打开工程", self.settings.get("project_dir", ""), "VoxMaster 工程 (*.voxproj)"
        )
        if p:
            self.open_path(p)

    def open_path(self, p):
        if not self.available(False):
            return
        p = Path(p).resolve()
        if p.suffix.lower() == PROJECT_EXT:
            try:
                d = load_project(p)
                refs = [(d, k) for k in ("source", "reference")] + [
                    (d["stems"], k) for k in d["stems"]
                ]
                if d.get("studio"):
                    ext = d["studio"].get("external_sources", {})
                    refs.extend((ext, k) for k in ext)
                for container, key in refs:
                    old = container[key]
                    if old and not Path(old).is_file():
                        new, _ = QFileDialog.getOpenFileName(
                            self, f"重新定位 {Path(old).name}", "", FORMATS
                        )
                        if not new:
                            return
                        container[key] = new
                self.rebuild(d, "恢复工程", reset=True, path=str(p))
            except Exception as exc:
                self.failed(str(exc))
        elif p.suffix.lower() in {".wav", ".aiff", ".aif", ".flac", ".mp3", ".m4a", ".aac", ".ogg"}:
            self.settings["import_dir"] = str(p.parent)
            doc = project(p, p.stem)
            doc["mode"] = self.mode()
            self.rebuild(doc, "正在读取音频", reset=True)
        else:
            self.notice("请选择 WAV、MP3、FLAC、M4A、AAC、OGG、AIFF 或 .voxproj 工程。")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            if url.isLocalFile():
                self.open_path(url.toLocalFile())
                break

    def save(self, as_new=False):
        if not self.available():
            return
        p = self.path
        if as_new or not p:
            suggested = Path(self.settings.get("project_dir", Path.home() / "Documents")) / (
                self.s.document["name"] + PROJECT_EXT
            )
            p, _ = QFileDialog.getSaveFileName(
                self, "保存工程", str(suggested), "VoxMaster 工程 (*.voxproj)"
            )
        if not p:
            return
        try:
            save_project(p, self.s.document)
            self.path = p
            warning = self.remember(p)
            self.refresh()
            self.progress_text.setText("工程已保存 · " + Path(p).name
                                       + (" · " + warning if warning else ""))
        except Exception as exc:
            self.failed(str(exc))

    def travel(self, redo):
        if not self.available(False):
            return
        a, b = (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        if not a:
            return
        old = self.s.document

        def done():
            a.pop()
            b.append(old)

        self.rebuild(copy.deepcopy(a[-1]), "重建历史版本", done=done)

    def current_params(self, *, with_reference=True):
        style = self.style.currentText()
        base = self.custom.get(style, style)
        report = self.s.vocal_report or self.s.analysis
        kind = self.kind.currentText()
        return tuning_plan(report, base, kind, self.s.reference_report if with_reference else None)

    def apply_params(self, params, caption, *, reference_match=False):
        d = copy.deepcopy(self.s.document)
        if reference_match and "before_reference" not in d:
            d["before_reference"] = {
                k: copy.deepcopy(d[k]) for k in ("params", "applied", "style", "kind")
            }
        d.update(
            params=params, style=self.style.currentText(), kind=self.kind.currentText(), applied=True
        )
        d["history"].append(clockstr() + "  " + caption)
        self.rebuild(d, caption)

    def tune(self):
        if not self.available():
            return
        try:
            self.apply_params(
                self.current_params(),
                "按测量值渲染 · " + self.style.currentText(),
                reference_match=bool(self.s.reference_report),
            )
        except Exception as exc:
            self.failed(str(exc))

    def parameters(self, tab=0):
        if not self.available():
            return
        params = self.s.document.get("params") or self.current_params()
        dlg = ParameterDialog(
            params,
            len(self.s.original) / SR,
            self,
            tab,
            report=self.s.vocal_report or self.s.analysis,
            audio=self.s.sources["Vocal"],
            sr=SR,
            cursor=self.cursor,
        )
        with managed_dialog(dlg):
            if dlg.exec():
                self.apply_params(dlg.value(), "应用效果器参数")

    def switch(self, wet):
        if not self.s or (wet and self.s.output is None):
            return
        playing = self.player.playing
        at = self.player.position if playing else self.cursor
        self.player.stop()
        self.listening = wet
        self.refresh()
        self.seek(at)
        if playing:
            self.start_playback()

    def seek(self, t):
        playing = self.player.playing
        if playing:
            self.player.stop()
        audio = self.audio()
        self.cursor = min(t, len(audio) / SR) if audio is not None else 0.0
        if playing:
            self.start_playback()
        self.tick()

    def region_selected(self, a, b):
        self.seek(a)
        self.progress_text.setText(f"试听区间   {timecode(a)} 至 {timecode(b)}")

    def start_playback(self):
        audio = self.audio()
        if audio is None:
            return
        end = len(audio) / SR
        start = self.cursor
        if self.timeline.region:
            lo, hi = self.timeline.region
            end = min(hi, end)
            if start < lo or start >= end:
                start = min(lo, end)
        if start >= end:
            start = 0
        try:
            self.player.play(audio, SR, start=start, end=end, loop=self.loop.isChecked())
            if self.player.device_notice:
                self.progress_text.setText(self.player.device_notice)
        except Exception as exc:
            self.failed("无法打开输出设备。" + str(exc))

    def set_monitor_volume(self, value):
        self.monitor_volume = value / 100
        self.set_monitor_gain()

    def set_monitor_gain(self, *_):
        gain = self.monitor_volume
        if self.s and self.s.measured and self.matched.isChecked():
            before, after = self.s.analysis["lufs"], self.s.measured["lufs"]
            if min(before, after) > -70:
                gain *= 10 ** ((min(before, after) - (after if self.listening else before)) / 20)
        self.player.volume = gain

    def play(self):
        if self.player.playing:
            self.cursor = self.player.position
            self.player.pause()
        else:
            self.start_playback()
        self.tick()

    def stop(self):
        self.player.stop()
        self.cursor = 0.0
        self.tick()

    def tick(self):
        message = self.player.poll_device()
        if message:
            self.progress_text.setText(message)
        audio = self.audio()
        if self.player.playing:
            self.cursor = self.player.position
            i = int(self.cursor * SR)
            block = audio[i : i + 2048] if audio is not None else np.empty((0, 2))
            self.spectrum.update_audio(block)
            peak = float(np.abs(block).max()) if len(block) else 0
            self.meter.setText(f"{20 * np.log10(max(peak, 1e-6)):.1f} dBFS")
        elif self.play_btn.text() == "Ⅱ  暂停":
            self.spectrum.update_audio([])
            self.meter.setText("— dBFS")
        self.play_btn.setText("Ⅱ  暂停" if self.player.playing else "▶  播放")
        self.clock.setText(timecode(self.cursor))
        if abs(self.timeline.cursor - self.cursor) > 1e-5:
            self.timeline.cursor = self.cursor
            self.timeline.update()

    def wave_menu(self, pos):
        menu = QMenu(self)
        for title, fn in [
            ("播放 / 暂停", self.play),
            ("清除选区", self.clear_region),
            ("编辑多轨", self.studio),
            ("撤销", lambda: self.travel(False)),
            ("重做", lambda: self.travel(True)),
        ]:
            menu.addAction(title, fn)
        with managed_dialog(menu):
            menu.exec(self.timeline.mapToGlobal(pos))

    def clear_region(self):
        self.timeline.region = None
        self.timeline.update()

    def projects(self):
        d = QDialog(self)
        d.setWindowTitle("我的项目")
        d.resize(620, 450)
        lay = QVBoxLayout(d)
        lay.addWidget(label("最近工程与恢复记录", "section"))
        files = QListWidget()
        recent = [Path(p) for p in self.recent_paths()]

        def modified(path):
            try:
                return path.stat().st_mtime
            except OSError:
                return float("-inf")

        try:
            recoveries = sorted(
                (ROOT / "recovery").glob("*.voxproj"), key=modified, reverse=True
            )[:20]
        except OSError:
            recoveries = []
        try:
            history = (
                sorted(Path(str(self.path) + ".history").glob("*.voxproj"), reverse=True)
                if self.path
                else []
            )
        except OSError:
            history = []
        for group, paths in [("工程", recent), ("备份", history), ("自动保存", recoveries)]:
            for path in paths:
                try:
                    title = load_project(path)["name"]
                    stamp = datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M")
                except Exception:
                    continue
                files.addItem(f"{group}    {title}    {stamp}")
                files.item(files.count() - 1).setData(Qt.UserRole, str(path))
                files.item(files.count() - 1).setToolTip(str(path))
        lay.addWidget(files)
        row = QHBoxLayout()
        lay.addLayout(row)

        def choose():
            item = files.currentItem()
            if item:
                d.accept()
                self.open_path(item.data(Qt.UserRole))

        def new():
            if not self.available(False):
                return
            d.accept()
            self.stop()
            self.s = None
            self.path = None
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.listening = False
            self.total.setText("/ 00:00.00")
            self.refresh()
            self.progress_text.setText("已新建空工程")

        files.itemDoubleClicked.connect(lambda _: choose())
        row.addWidget(button("新建工程", new))
        row.addWidget(button("从磁盘打开", lambda: (d.accept(), self.open_project())))
        row.addStretch()
        row.addWidget(button("打开所选版本", choose))
        with managed_dialog(d):
            d.exec()

    def report_text(self, title, content):
        d = QDialog(self)
        d.setWindowTitle(title)
        d.resize(590, 510)
        lay = QVBoxLayout(d)
        box = QPlainTextEdit()
        box.setPlainText(content)
        box.setReadOnly(True)
        lay.addWidget(box)
        lay.addWidget(button("关闭", d.accept))
        with managed_dialog(d):
            d.exec()

    def report_view(self):
        if not self.s:
            return
        r = self.s.measured if self.listening and self.s.measured else self.s.analysis
        bands = {
            "rumble": "超低频",
            "body": "低频厚度",
            "mud": "低中频",
            "presence": "清晰度频段",
            "air": "空气感频段",
            "sibilance": "齿音频段",
        }
        lines = [
            r["classification"],
            *r["diagnostics"],
            "",
            f"RMS   {r['rms_db']:.2f} dBFS     样本峰值   {r['peak_db']:.2f} dBFS",
            f"活动帧动态跨度   {r['dynamic_db']:.1f} dB",
            f"安静帧电平估计   {r['noise_db']:.1f} dBFS",
            f"侧声道能量占比   {r['side_fraction']:.1%}",
            f"节奏   {r.get('bpm') or '未确定'}     调性   {r.get('key') or '未确定'}",
            "",
            "各频带相对功率",
        ]
        lines += [f"{bands.get(k, k)}    {v:.1f} dB" for k, v in r["bands_db"].items()]
        lines += ["", *report_lines(r), "", "工程处理历史", *self.s.document.get("history", [])]
        dialog = ReportDialog(self.s, r, "\n".join(lines), self)
        with managed_dialog(dialog):
            if dialog.exec() and dialog.stage:
                start, end = self.timeline.region or (self.cursor, self.cursor + 6.0)
                self.preview_reference(start, end, stage=dialog.stage)
            elif dialog.result() and dialog.interval:
                self.timeline.region = dialog.interval
                self.player.stop()
                self.seek(dialog.interval[0])
                self.start_playback()

    def reference(self):
        if not self.available():
            return
        s = self.s
        d = QDialog(self)
        d.setWindowTitle("参考音频匹配")
        d.setMinimumWidth(490)
        box = QVBoxLayout(d)
        box.addWidget(label("参考音频匹配", "section"))
        ref = s.reference_report
        if ref:
            src = s.vocal_report or s.analysis
            box.addWidget(label(Path(s.document["reference"]).name))
            form = QGridLayout()
            box.addLayout(form)
            for col, text in enumerate(("指标", "原始录音", "参考作品")):
                form.addWidget(label(text, "sub"), 0, col)
            metrics = [
                ("综合响度", "lufs", " LUFS"),
                ("动态跨度", "dynamic_db", " dB"),
                ("侧声道能量比", "side_fraction", ""),
            ]
            for i, (desc, key, unit) in enumerate(metrics, 1):
                for j, text in enumerate((desc, f"{src[key]:.2f}{unit}", f"{ref[key]:.2f}{unit}")):
                    form.addWidget(label(text), i, j)
            for i, (key, desc) in enumerate(
                [("body", "低频厚度"), ("mud", "低中频"), ("presence", "清晰度"), ("air", "空气感")],
                4,
            ):
                for j, text in enumerate(
                    (desc, f"{src['bands_db'][key]:.1f} dB", f"{ref['bands_db'][key]:.1f} dB")
                ):
                    form.addWidget(label(text), i, j)
            rows = comparison(src, ref)
            roles = choices(["整轨"] + [row["role"] for row in rows])
            box.addWidget(roles)
            details = QPlainTextEdit()
            details.setReadOnly(True)
            box.addWidget(details)

            def show_comparison(index):
                text = (
                    describe_match(rows[index - 1])
                    if index
                    else "\n".join(compare_lines(src, ref) + space_notes(src, ref))
                )
                details.setPlainText(text)
                listen.setEnabled(not index or "interval" in rows[index - 1])

            def preview():
                index = roles.currentIndex()
                a, b = rows[index - 1]["interval"] if index else (self.cursor, self.cursor + 6.0)
                d.accept()
                self.preview_reference(a, b)

            listen = button("等响试听匹配建议", preview)
            box.addWidget(listen)
            roles.currentIndexChanged.connect(show_comparison)
            show_comparison(0)
            box.addWidget(button("按参考特征调音", lambda: (d.accept(), self.tune()), "primary"))
        else:
            box.addWidget(label("载入参考作品，比较响度、动态、频带功率与立体声宽度。"))

        def change(clear=False):
            path = "" if clear else QFileDialog.getOpenFileName(d, "选择参考作品", "", FORMATS)[0]
            if not path and not clear:
                return
            d.accept()
            doc = copy.deepcopy(s.document)
            doc["reference"] = path
            self.rebuild(doc, "更新参考分析")

        box.addWidget(button("选择参考音频", change))
        if "before_reference" in s.document:

            def restore():
                d.accept()
                doc = copy.deepcopy(s.document)
                doc.update(doc.pop("before_reference"))
                doc["reference"] = ""
                doc["history"].append(clockstr() + "  恢复匹配前参数")
                self.rebuild(doc, "恢复匹配前参数")

            box.addWidget(button("恢复匹配前参数并移除参考", restore))
        if ref:
            box.addWidget(button("移除参考", lambda: change(True)))
        with managed_dialog(d):
            d.exec()

    def preview_reference(self, start, end, stage=None):
        from .analysis import loudness
        from .tail011 import slice_params

        source = self.s.sources["Vocal"]
        final = len(source) / SR
        start = float(np.clip(start - 0.35, 0, max(0, final - 0.5)))
        end = min(final, max(start + 1.5, min(start + 8, end + 0.5)))
        params = slice_params(
            self.s.document["params"] if stage else self.current_params(), start, end
        )
        baseline = (
            None if stage else slice_params(self.current_params(with_reference=False), start, end)
        )
        self.stop()

        def render(cancel, progress):
            dry = source[round(start * SR) : round(end * SR)]
            tapped = []

            def capture(name, before, after):
                if name == stage:
                    tapped.extend((before, after))

            wet = engine.process(dry, SR, params, cancel, progress, tap=capture if stage else None)
            buffers = tapped if stage else (engine.process(dry, SR, baseline, cancel), wet)
            if len(buffers) != 2:
                raise ValueError("这次渲染旁通了所选模块。")
            return buffers, [loudness(x, SR, cancel) for x in buffers]

        def ready(result):
            buffers, levels = result
            with managed_dialog(PreviewDialog(
                buffers, levels, SR, self.player.device, self.monitor_volume, self, stage
            )) as dialog:
                dialog.exec()

        self.run_job("渲染模块试听片段" if stage else "渲染参考匹配试听片段", render, ready)

    def models(self):
        from .models import ModelDialog

        with managed_dialog(ModelDialog(self)) as dialog:
            dialog.exec()

    def has_song_stems(self):
        stems = self.s.document.get("stems", {})
        # The default Vocal buffer is the original mix, not a separated stem.
        return all(stems.get(role) and role in self.s.sources for role in STEM_ROLES)

    def separation_model_ready(self):
        from . import models_store

        def installed():
            root = models_store.directory()
            return all(models_store.size_of(root / name) == spec[0]
                       for name, spec in models_store.FILES.items())

        if installed():
            return True
        if QMessageBox.question(
            self, "需要本地分离模型",
            "模型缺失或不完整。打开模型中心，由你选择下载或导入？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return False
        self.models()
        if installed():
            return True
        self.progress_text.setText("未安装完整模型，未开始分轨。")
        return False

    def separation_destination(self):
        return QFileDialog.getExistingDirectory(
            self, "选择分轨输出目录", self.settings.get("export_dir", "")
        )

    def song_mix(self):
        if not self.available():
            return
        current = self.s
        doc = current.document
        has_stems = self.has_song_stems()
        has_studio = doc.get("studio") is not None
        if not has_stems and (has_studio or doc.get("stems")):
            self.notice(
                "当前工程含多轨编辑或已有分轨，但缺少可用的双轨。整曲处理不会替换这些素材。"
                "请重新定位原分轨，或在备份工程后从「人声分离」明确执行重新分轨。"
            )
            return
        styles = list(engine.PRESETS)
        plan = doc.get("song")
        style = doc["style"]
        if plan and style not in styles:
            styles.append(style)
        try:
            recommend = False
            while True:
                dialog = SongDialog(
                    styles, style, has_stems=has_stems, plan=plan, recommend=recommend,
                    replaces_vocal=bool(doc.get("applied") and not plan),
                    has_studio=has_studio, parent=self,
                )
                with managed_dialog(dialog):
                    if not dialog.exec():
                        return
                    if dialog.recommend_again:
                        recommend = True
                        continue
                    options = dialog.options()
                    break
            if has_stems:
                work = lambda cancel, pg: service.plan_song(current, cancel, pg, **options)
                stage = "应用整曲方案" if "plan" in options else "分析分轨并推荐整曲方案"
            else:
                if not self.separation_model_ready():
                    return
                dest = self.separation_destination()
                if not dest:
                    return
                work = lambda cancel, pg: service.separate_project(
                    current, dest, cancel, pg, song_options=options,
                )
                stage = "本地分轨 → 整曲分析 → 混音与母带"
            self.run_job(stage, work, self.commit_render)
        except Exception as exc:
            self.failed(str(exc))

    def commit_render(self, session):
        try:
            self.commit(session)
        except OSError as exc:
            if session.publication_committed and session.publication_project:
                raise OSError(
                    f"{exc}\n分轨已完成，但会话提交失败。可从以下工程恢复分轨与方案：\n"
                    f"{session.publication_project}"
                ) from exc
            raise
        self.show_ready(session)

    def separate(self):
        if not self.available():
            return
        current = self.s
        doc = current.document
        edited = doc.get("studio") is not None or doc.get("applied") or doc.get("song")
        if edited or doc.get("stems"):
            if QMessageBox.question(
                self, "重新分轨",
                "分离会替换本工程使用的分轨，并重置多轨时间轴、人声调音与整曲方案。"
                "不会覆盖旧音频文件，可撤销。继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
        try:
            if not self.separation_model_ready():
                return
            dest = self.separation_destination()
            if dest:
                self.run_job(
                    "分离人声与伴奏",
                    lambda cancel, pg: service.separate_project(
                        current, dest, cancel, pg, song_options=None,
                    ),
                    self.commit_render,
                )
        except Exception as exc:
            self.failed(str(exc))

    def studio(self):
        if not self.available():
            return
        from .studio import StudioDialog

        self.stop()
        mix_sources = self.s.mix_sources
        tracks = dict(mix_sources if mix_sources is not None else self.s.sources)
        if mix_sources is None and self.s.tuned_vocal is not None:
            tracks["Vocal"] = self.s.tuned_vocal
        try:
            d = StudioDialog(tracks, SR, self, state=copy.deepcopy(self.s.document.get("studio")))
            with managed_dialog(d):
                if mix_sources is not None:
                    hint = label("试听包含整曲处理后的分轨。应用混音后，最终母带在多轨总线之后处理。", "sub")
                    hint.setWordWrap(True)
                    hint.setContentsMargins(20, 8, 20, 0)
                    d.layout().insertWidget(0, hint)
                d.player.device = self.player.device
                d.player.volume = self.monitor_volume
                if d.exec():
                    doc = copy.deepcopy(self.s.document)
                    doc["studio"] = d.state
                    doc["history"].append(clockstr() + "  应用多轨编辑")
                    self.rebuild(doc, "应用多轨混音")
        except Exception as exc:
            self.failed(str(exc))

    def library(self):
        d = QDialog(self)
        d.setWindowTitle("调音风格库")
        d.resize(560, 530)
        l = QVBoxLayout(d)
        lst = QListWidget()
        l.addWidget(lst)

        def reload(name):
            lst.clear()
            lst.addItems(list(engine.PRESETS) + list(self.custom))
            found = lst.findItems(name, Qt.MatchExactly)
            lst.setCurrentItem(found[0] if found else lst.item(0))

        reload(self.style.currentText())

        def selected():
            return lst.currentItem().text()

        def data():
            return copy.deepcopy(self.custom.get(selected(), engine.PRESETS.get(selected())))

        def add(value, default):
            name, ok = QInputDialog.getText(d, "保存风格", "我的风格名称", text=default)
            if not ok or not name.strip():
                return
            name = name.strip()
            if name in engine.PRESETS:
                return self.notice("内置名称已被使用，请换一个名称。")
            if (
                name in self.custom
                and QMessageBox.question(d, "更新风格", "覆盖已保存的同名风格？") != QMessageBox.Yes
            ):
                return
            p = engine.normalize(value)
            p["tail_times"] = []
            for key in ("automation", "pitch_regions", "tail_regions"):
                p.pop(key, None)
            self.custom[name] = p
            self.settings["presets"] = self.custom
            self.save_settings()
            if self.style.findText(name) < 0:
                self.style.addItem(name)
            reload(name)

        def activate():
            self.style.setCurrentText(selected())
            d.accept()
            if self.s:
                self.tune()

        def export_style():
            p, _ = QFileDialog.getSaveFileName(
                d, "导出风格", selected() + ".voxpreset", "调音风格 (*.voxpreset)"
            )
            if p and Path(p).suffix.lower() == ".voxpreset":
                write_json(p, {"version": 1, "name": selected(), "params": data()})

        def import_style():
            p, _ = QFileDialog.getOpenFileName(d, "导入风格", "", "调音风格 (*.voxpreset)")
            if p:
                try:
                    v = read_json(p)
                    if v.get("version") != 1:
                        raise ValueError("不支持此预设版本。")
                    add(
                        engine.normalize(v["params"]),
                        v["name"] + " 副本" if v["name"] in engine.PRESETS else v["name"],
                    )
                except Exception as exc:
                    self.failed(str(exc))

        grid = QGridLayout()
        l.addLayout(grid)
        for i, (caption, fn) in enumerate(
            [
                ("使用并试听", activate),
                ("复制为我的风格", lambda: add(data(), selected() + " 副本")),
                (
                    "保存当前调音",
                    lambda: (
                        add(self.s.document.get("params") or self.current_params(), "我的调音")
                        if self.s
                        else self.notice("请先载入录音。")
                    ),
                ),
                ("恢复内置默认", lambda: restore()),
                ("从文件导入", import_style),
                ("导出所选风格", export_style),
            ]
        ):
            grid.addWidget(button(caption, fn), i // 3, i % 3)

        def restore():
            choice, ok = QInputDialog.getItem(
                d, "恢复默认", "选择内置风格", list(engine.PRESETS), 0, False
            )
            if ok:
                reload(choice)
                self.style.setCurrentText(choice)
                if self.s:
                    d.accept()
                    self.tune()

        lst.itemDoubleClicked.connect(lambda _: activate())
        with managed_dialog(d):
            d.exec()

    def export(self):
        if not self.available():
            return
        if self.s.output is None:
            return self.notice("请先执行一次调音，或在专业混音台应用混音。")
        source = self.s.output
        dlg = ExportDialog(len(source) / SR, self.s.measured, self)
        with managed_dialog(dlg):
            if not dlg.exec():
                return
            fmt, rate, bits, ch = dlg.value()
        base = Path(self.settings.get("export_dir") or Path.home() / "Music")
        target = base / (Path(self.s.document["source"]).stem + " - 调音." + fmt)
        path, _ = QFileDialog.getSaveFileName(
            self, "导出音频到新文件", str(target), f"{fmt.upper()} (*.{fmt})"
        )
        if not path:
            return
        if Path(path).suffix.lower() != "." + fmt:
            return self.notice("目标文件扩展名与所选格式不符。")
        def encode(cancel, _progress):
            result = audioio.encode(path, source, SR, bits, cancel, output_rate=rate, channels=ch)
            # Keep encoder receipts and warnings; legacy encoders returned no receipt.
            # A late cancellation cannot undo the completed no-replace publication.
            return result if result is not None else PublishedFile(Path(path))

        self.run_job(
            "编码成品",
            encode,
            lambda result: self.progress_text.setText(
                "已导出 · " + str(result.path)
                + ("\n" + result.warning if getattr(result, "warning", None) else "")
            ),
        )

    def settings_view(self):
        from .settings_dialog import SettingsDialog

        d = SettingsDialog(self.settings, self.device_report, self)
        with managed_dialog(d):
            if d.exec():
                previous_settings = self.settings
                previous_theme = previous_settings.get("theme", "system")
                previous_device = self.player.device
                previous_cache = audioio.cache_directory()
                try:
                    new = d.value()
                    audioio.set_cache_directory(new.get("cache_dir"))
                    self.player.device = hardware.resolve_output(new, self.device_report)
                    self.settings = new
                    self.show_device_names()
                    self.save_settings()
                    theme_manager().set_mode(new.get("theme", "system"))
                except Exception as exc:
                    self.settings = previous_settings
                    self.player.device = previous_device
                    self.show_device_names()
                    theme_manager().set_mode(previous_theme)
                    message = str(exc)
                    try:
                        audioio.set_cache_directory(previous_cache)
                    except OSError as rollback_error:
                        message += "\n恢复音频缓存目录失败：" + str(rollback_error)
                    self.failed(message)

    def closeEvent(self, event):
        if self.worker:
            self.cancel()
            self.progress_text.setText("正在取消当前任务，完成后可关闭窗口。")
            event.ignore()
            return
        self.player.stop()
        if getattr(self, "hardware_job", None) and self.hardware_job.isRunning():
            event.ignore()
            self.hardware_job.finished.connect(self.close)
            return
        event.accept()
