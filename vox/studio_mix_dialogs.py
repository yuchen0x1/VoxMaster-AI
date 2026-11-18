"""Native controls for measured mix suggestions and serial insert processing."""

import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
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
    QVBoxLayout,
    QWidget,
)

from .studio_effects import INSERTS, INSERT_RANGES
from .studio_timeline import TRACK_LABELS


def spin(lo, hi, val, suffix="", digits=1):
    item = QDoubleSpinBox()
    item.setRange(lo, hi)
    item.setDecimals(digits)
    item.setValue(val)
    item.setSuffix(suffix)
    item.setSingleStep(0.1 if digits else 1.0)
    return item


def buttons(dialog, layout):
    bar = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bar.button(QDialogButtonBox.Ok).setText("应用")
    bar.button(QDialogButtonBox.Cancel).setText("取消")
    bar.accepted.connect(dialog.accept)
    bar.rejected.connect(dialog.reject)
    layout.addWidget(bar)


class RackDialog(QDialog):
    def __init__(self, session, target, parent):
        super().__init__(parent)
        self.setWindowTitle("轨道与总线效果器")
        self.resize(420, 420)
        layout = QVBoxLayout(self)
        self.session = session
        self.target = QComboBox()
        for key, name in TRACK_LABELS.items():
            self.target.addItem(name, key)
        layout.addWidget(self.target)
        self.target.setCurrentIndex(self.target.findData(target))
        self.order = QListWidget()
        self.order.setAccessibleName("串联效果器，勾选以启用")
        layout.addWidget(self.order)
        row = QHBoxLayout()
        for name, delta in (("上移", -1), ("下移", 1)):
            b = QPushButton(name)
            b.clicked.connect(lambda _, d=delta: self.move(d))
            row.addWidget(b)
        layout.addLayout(row)
        form = QFormLayout()
        self.values = {}
        for k, (lo, hi, neutral) in INSERT_RANGES.items():
            widget = spin(
                lo,
                hi,
                neutral,
                " 倍" if k == "width" else " dB",
                2 if k == "width" else 1,
            )
            self.values[k] = widget
            form.addRow(
                {"presence": "2.8 kHz EQ", "compress": "压缩最大衰减", "width": "宽度"}[k],
                widget,
            )
        layout.addLayout(form)
        self.drafts = copy.deepcopy(session.state["racks"])
        self.previous = None
        self.target.currentIndexChanged.connect(self.load)
        self.load()
        buttons(self, layout)

    def capture(self):
        if self.previous is None:
            return
        items = [self.order.item(i) for i in range(self.order.count())]
        self.drafts[self.previous] = {
            **{k: v.value() for k, v in self.values.items()},
            "order": [x.data(Qt.UserRole) for x in items],
            "bypass": [x.data(Qt.UserRole) for x in items if x.checkState() != Qt.Checked],
        }

    def load(self):
        self.capture()
        self.previous = self.target.currentData()
        rack = self.drafts[self.previous]
        self.order.clear()
        for k in rack["order"]:
            item = QListWidgetItem(INSERTS[k])
            item.setData(Qt.UserRole, k)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if k in rack["bypass"] else Qt.Checked)
            self.order.addItem(item)
        self.order.setCurrentRow(0)
        for k, widget in self.values.items():
            widget.setValue(rack[k])

    def move(self, d):
        i = self.order.currentRow()
        if 0 <= i + d < self.order.count():
            item = self.order.takeItem(i)
            self.order.insertItem(i + d, item)
            self.order.setCurrentRow(i + d)

    def accept(self):
        self.capture()
        if self.drafts != self.session.state["racks"]:
            self.session.checkpoint()
            self.session.state["racks"] = copy.deepcopy(self.drafts)
        super().accept()


class BalanceDialog(QDialog):
    def __init__(self, session, report, parent):
        super().__init__(parent)
        self.session = session
        self.report = report
        self.setWindowTitle("自动平衡与响度匹配")
        self.resize(540, 495)
        root = QVBoxLayout(self)
        for key, row in report["tracks"].items():
            lufs = "低于门限" if row["lufs"] is None else f"{row['lufs']:.1f} LUFS"
            corr = "—" if row["correlation"] is None else f"{row['correlation']:+.2f}"
            mono = "—" if row["mono_db"] is None else f"{row['mono_db']:.1f} dB"
            warn = (
                "  ·  单声道抵消风险" if row["mono_db"] is not None and row["mono_db"] < -6 else ""
            )
            root.addWidget(
                QLabel(f"{TRACK_LABELS[key]}    {lufs}    相关度 {corr}    折叠 {mono}{warn}")
            )
        self.mode = QComboBox()
        self.mode.addItem("人声与伴奏平衡")
        self.mode.addItem("匹配目标响度")
        root.addWidget(self.mode)
        self.balance_page = QWidget()
        f = QFormLayout(self.balance_page)
        suggestion = report["recommendation"]
        current = session.state["routing"]
        routing = suggestion["routing"] if suggestion and not current["enabled"] else current
        original = session.strip("Instrumental")["gain"]
        self.info = QLabel()
        self.info.setWordWrap(True)
        if suggestion:
            low, high = suggestion["band"]
            self.info.setText(
                f"重叠活动窗 {suggestion['overlap_frames']} 个，人声 {suggestion['vocal_db']:.1f}、伴奏 {suggestion['music_db']:.1f} dBFS RMS。共享能量最高的频带为 {low}–{high} Hz。"
            )
        else:
            self.info.setText("人声与伴奏的同时活动窗不足。可手动设置路由，或选择响度匹配。")
        f.addRow(self.info)
        self.gain = spin(-60, 12, suggestion["music_gain"] if suggestion else original, " dB")
        f.addRow("伴奏电平", self.gain)
        self.enabled = QCheckBox("启用人声侧链与居中路由")
        self.enabled.setChecked(routing["enabled"])
        f.addRow(self.enabled)
        self.routing = {}
        for k, label, lo, hi, suffix, digits in (
            ("duck_db", "伴奏整体避让上限", 0, 8, " dB", 1),
            ("mask_db", "冲突频带衰减上限", 0, 8, " dB", 1),
            ("frequency", "避让中心频率", 150, 6000, " Hz", 0),
            ("threshold", "人声侧链触发电平", -80, -6, " dBFS", 1),
            ("center", "人声宽度收窄量", 0, 1, "", 2),
        ):
            self.routing[k] = spin(lo, hi, routing[k], suffix, digits)
            f.addRow(label, self.routing[k])
        self.recenter = QCheckBox("将人声声像移到正中")
        self.recenter.setChecked(bool(suggestion and self.enabled.isChecked()))
        f.addRow(self.recenter)
        root.addWidget(self.balance_page)
        self.match_page = QWidget()
        form = QFormLayout(self.match_page)
        self.match_track = QComboBox()
        for key, val in report["tracks"].items():
            if val["lufs"] is not None:
                self.match_track.addItem(TRACK_LABELS[key], key)
        self.target = spin(-60, -5, -18, " LUFS")
        self.match_result = QLabel()
        self.match_result.setWordWrap(True)
        self.match_track.currentIndexChanged.connect(self.show_delta)
        self.target.valueChanged.connect(self.show_delta)
        form.addRow("调整通道", self.match_track)
        form.addRow("目标综合响度", self.target)
        form.addRow(self.match_result)
        root.addWidget(self.match_page)
        self.has_pair = all(k in report["tracks"] for k in ("Vocal", "Instrumental"))
        if not self.has_pair:
            self.mode.model().item(0).setEnabled(False)
            self.mode.setCurrentIndex(1)
        self.mode.currentIndexChanged.connect(self.show_mode)
        self.show_mode()
        buttons(self, root)

    def show_mode(self):
        self.balance_page.setVisible(self.mode.currentIndex() == 0)
        self.match_page.setVisible(self.mode.currentIndex() == 1)
        self.show_delta()

    def show_delta(self):
        key = self.match_track.currentData()
        if key is None:
            self.match_result.setText("所有通道均低于响度门限。")
            return
        measured = self.report["tracks"][key]["lufs"]
        current = (
            self.session.state["master_db"] if key == "Master" else self.session.strip(key)["gain"]
        )
        change = min(9.0, self.target.value() - measured)
        self.new_gain = float(min(12, max(-60, current + change)))
        self.match_result.setText(
            f"当前 {measured:.1f} LUFS，通道推子 {current:+.1f} → {self.new_gain:+.1f} dB。单次提升限制 9 dB；总线峰值保护及动态效果可能限制最终响度。"
        )

    def accept(self):
        if self.mode.currentIndex() == 0:
            settings = {k: ctl.value() for k, ctl in self.routing.items()}
            settings["enabled"] = self.enabled.isChecked()
            self.session.configure_balance(
                settings, self.gain.value(), 0.0 if self.recenter.isChecked() else None
            )
        else:
            key = self.match_track.currentData()
            if key is not None:
                self.session.set_param(
                    key, "master_db" if key == "Master" else "gain", self.new_gain
                )
        super().accept()
