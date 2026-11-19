import copy
from contextlib import contextmanager
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from .engine import PARAMS, normalize
from .analysis import NOTES
from .dsp_panel import EqEditor, MeterPanel
from .visual import timecode

STAGES = {
    "denoise": "降噪",
    "pitch": "音高",
    "eq": "均衡器",
    "compress": "压缩器",
    "deess": "齿音控制",
    "saturate": "饱和",
    "space": "混响与尾音",
    "stereo": "立体声",
    "master": "母带",
}


@contextmanager
def managed_dialog(dialog):
    """Dispose a transient native widget after its modal results have been read."""
    try:
        yield dialog
    finally:
        dialog.deleteLater()


def confirm(layout, dialog):
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.button(QDialogButtonBox.Ok).setText("应用")
    buttons.button(QDialogButtonBox.Cancel).setText("取消")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)


def choices(items, current=None):
    box = QComboBox()
    box.addItems([str(i) for i in items])
    if current is not None:
        box.setCurrentText(str(current))
    return box


def label(text, role=None):
    widget = QLabel(text)
    if role:
        widget.setObjectName(role)
    return widget


class ParameterDialog(QDialog):
    def __init__(
        self, params, duration, parent=None, tab=0, *, audio=None, report=None, sr=44100, cursor=0
    ):
        super().__init__(parent)
        self.setWindowTitle("效果器工作室")
        self.resize(560, 610)
        params = normalize(params)
        self.base = copy.deepcopy(params)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        self.inputs = {}
        self.enums = {}
        families = {
            "hum_hz": ("工频嗡声抑制", ((0, "关闭"), (50, "50 Hz"), (60, "60 Hz"))),
            "room_type": (
                "空间类型",
                (
                    ("Studio", "录音棚"),
                    ("Room", "房间"),
                    ("Plate", "板式"),
                    ("Spring", "弹簧"),
                    ("Hall", "大厅"),
                    ("Large Space", "大型空间"),
                    ("Dark Hall", "暗色厅堂"),
                    ("Bright Hall", "明亮厅堂"),
                ),
            ),
            "reverb_send": ("混响范围", (("Full", "全轨"), ("Tails", "仅句尾"))),
            "delay_type": (
                "延迟类型",
                (
                    ("Slapback", "单次回声"),
                    ("Ping-Pong", "左右交替"),
                    ("Stereo", "立体声"),
                    ("Tempo", "拍点同步"),
                ),
            ),
            "beat_fraction": (
                "同步音符",
                ((1.0, "四分音符"), (0.5, "八分音符"), (0.25, "十六分音符")),
            ),
            "saturation_type": (
                "谐波类型",
                (
                    ("Tape", "磁带"),
                    ("Tube", "电子管"),
                    ("Soft Clip", "软削波"),
                    ("Exciter", "高频激励"),
                    ("Radio", "收音机"),
                    ("Megaphone", "扩音器"),
                ),
            ),
            "key": ("调性主音", [("Auto", "未指定")] + [(note, note) for note in NOTES]),
            "scale": ("音阶", (("Chromatic", "半音阶"), ("Major", "大调"), ("Minor", "小调"))),
        }
        for key, (caption, options) in families.items():
            enum = QComboBox()
            for value, name in options:
                enum.addItem(name, value)
            enum.setCurrentIndex(max(0, enum.findData(params.get(key))))
            form.addRow(caption, enum)
            self.enums[key] = enum
        for key, (caption, lo, hi, step) in PARAMS.items():
            if key not in params:
                continue
            val = QDoubleSpinBox()
            val.setRange(lo, hi)
            val.setDecimals(3 if step < 0.01 else 2)
            val.setSingleStep(step)
            val.setValue(params[key])
            form.addRow(caption, val)
            self.inputs[key] = val
        noise_choice = QComboBox()
        for name, amount in (
            ("当前方案", params["denoise"]),
            ("轻度", 0.22),
            ("标准", 0.48),
            ("强力", 0.82),
        ):
            noise_choice.addItem(name, amount)
        noise_choice.activated.connect(
            lambda i: self.inputs["denoise"].setValue(noise_choice.itemData(i))
        )
        form.insertRow(0, "降噪力度预选", noise_choice)
        target = QComboBox()
        for caption, lufs in (
            ("当前方案", params["target_lufs"]),
            ("网络发布 · −14 LUFS", -14),
            ("短视频 · −16 LUFS", -16),
            ("音乐播放 · −18 LUFS", -18),
            ("动态 WAV · −20 LUFS", -20),
        ):
            target.addItem(caption, lufs)
        target.setToolTip("工作室建议起点，可在目标 LUFS 参数中自定义。")
        target.activated.connect(lambda i: self.inputs["target_lufs"].setValue(target.itemData(i)))
        form.insertRow(1, "母带目标", target)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, "处理参数")
        chain = QWidget()
        box = QVBoxLayout(chain)
        box.addWidget(label("拖动调整处理顺序，勾选启用效果器。", "sub"))
        self.chain = QListWidget()
        self.chain.setDragDropMode(QAbstractItemView.InternalMove)
        for stage in params.get("order", STAGES):
            item = QListWidgetItem(STAGES.get(stage, stage), self.chain)
            item.setData(Qt.UserRole, stage)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if stage in params.get("disabled", []) else Qt.Checked)
        box.addWidget(self.chain)
        self.tabs.addTab(chain, "链路")
        tail = QWidget()
        box = QVBoxLayout(tail)
        box.addWidget(label("在句末发送延迟。混响范围可在参数页切换为仅句尾。", "sub"))
        self.times = QListWidget()
        self.times.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for t in params.get("tail_times", []):
            self.add_time(float(t))
        box.addWidget(self.times)
        row = QHBoxLayout()
        self.time = QDoubleSpinBox()
        self.time.setRange(0, duration)
        self.time.setSuffix(" s")
        row.addWidget(self.time)
        add = QPushButton("添加位置")
        add.clicked.connect(lambda: self.add_time(self.time.value()))
        row.addWidget(add)
        rm = QPushButton("移除所选")
        rm.clicked.connect(self.remove_time)
        row.addWidget(rm)
        box.addLayout(row)
        self.tabs.addTab(tail, "尾音位置")
        eq_page = QWidget()
        eq_layout = QVBoxLayout(eq_page)
        eq_layout.addWidget(label("拖动频段控制点调整频率与增益，或在处理参数页输入数值。", "sub"))
        eq_layout.addWidget(EqEditor(self.inputs, sr), 1)
        self.tabs.addTab(eq_page, "EQ 曲线")
        self.meters = None
        self.automation_page = None
        self.phrase_editor = None
        if audio is not None and report is not None:
            self.meters = MeterPanel(audio, sr, report, cursor, self.value)
            self.tabs.addTab(self.meters, "音高与压缩")
            for box in self.inputs.values():
                box.valueChanged.connect(lambda _: self.meters.schedule())
            for enum in self.enums.values():
                enum.currentIndexChanged.connect(lambda _: self.meters.schedule())
            from .pitch_tail_editor import PitchTailEditor
            from .review import AutomationPage

            self.phrase_editor = PitchTailEditor(audio, sr, report, params, self.value, parent=self)
            self.tabs.addTab(self.phrase_editor, "音高与尾音编辑")
            self.finished.connect(lambda _: self.phrase_editor.shutdown())
            if params.get("automation"):
                self.automation_page = AutomationPage(
                    params["automation"], report.get("segments", [])
                )
                self.tabs.addTab(self.automation_page, "分段参数")
        self.tabs.setCurrentIndex(tab)
        confirm(layout, self)

    def add_time(self, t):
        item = QListWidgetItem(f"{timecode(t)}     {t:.3f} s", self.times)
        item.setData(Qt.UserRole, t)

    def remove_time(self):
        for item in self.times.selectedItems():
            self.times.takeItem(self.times.row(item))

    def value(self):
        data = copy.deepcopy(self.base)
        data.update({key: box.value() for key, box in self.inputs.items()})
        data.update({key: box.currentData() for key, box in self.enums.items()})
        items = [self.chain.item(i) for i in range(self.chain.count())]
        data["order"] = [i.data(Qt.UserRole) for i in items]
        data["disabled"] = [i.data(Qt.UserRole) for i in items if i.checkState() != Qt.Checked]
        data["tail_times"] = sorted(
            set(self.times.item(i).data(Qt.UserRole) for i in range(self.times.count()))
        )
        if self.phrase_editor:
            data.update(self.phrase_editor.value())
        if self.automation_page:
            data["automation"] = copy.deepcopy(self.automation_page.controls)
        return data


class ExportDialog(QDialog):
    def __init__(self, seconds, report, parent):
        super().__init__(parent)
        self.setWindowTitle("导出成品")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.format = choices(["WAV", "FLAC", "MP3", "AAC"])
        self.rate = choices([44100, 48000, 88200, 96000])
        self.bits = choices([16, 24, "32 Float"], 24)
        self.channels = choices(["立体声", "单声道"])
        for name, w in [
            ("文件格式", self.format),
            ("采样率 · Hz", self.rate),
            ("PCM 位深", self.bits),
            ("声道", self.channels),
        ]:
            form.addRow(name, w)
        self.info = label("")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.seconds = seconds
        self.report = report
        self.format.currentTextChanged.connect(self.update_format)
        for box in (self.rate, self.bits, self.channels):
            box.currentTextChanged.connect(self.update_info)
        self.update_format()
        confirm(layout, self)

    def update_format(self, *_):
        fmt = self.format.currentText()
        rate = self.rate.currentText()
        self.rate.clear()
        self.rate.addItems(["44100", "48000"] + ([] if fmt == "MP3" else ["88200", "96000"]))
        self.rate.setCurrentText(rate)
        bits = self.bits.currentText()
        self.bits.clear()
        self.bits.addItems(["16", "24"] + (["32 Float"] if fmt == "WAV" else []))
        self.bits.setCurrentText(bits)
        self.bits.setEnabled(fmt in ("WAV", "FLAC"))
        self.update_info()

    def update_info(self, *_):
        if not self.rate.currentText() or not self.bits.currentText():
            return
        from .audioio import estimate_size

        fmt, rate, bits, channels = self.value()
        size = estimate_size(self.seconds, fmt, rate, bits, channels)
        self.info.setText(
            f"渲染总线   {self.report['lufs']:.1f} LUFS    {self.report['true_peak_db']:.1f} dBTP\n预计文件大小   {size / 1048576:.2f} MiB"
        )

    def value(self):
        return (
            self.format.currentText().lower(),
            int(self.rate.currentText()),
            int(self.bits.currentText().split()[0]),
            2 - self.channels.currentIndex(),
        )
