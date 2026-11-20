"""Segment inspection, bounded automation editing, and matched listening."""

from copy import deepcopy
import numpy as np
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from .visual import timecode
from .playback import Playback
from .segments import CONTROLS

FIELDS = {
    "body_delta_db": "厚度 EQ · dB",
    "mud_delta_db": "低中频 EQ · dB",
    "presence_delta_db": "清晰度 EQ · dB",
    "air_delta_db": "高频 EQ · dB",
    "ratio_scale": "压缩比倍率",
    "threshold_delta_db": "压缩阈值偏移 · dB",
    "denoise_scale": "降噪混合比例",
    "space_scale": "空间返回比例",
    "transient_protect": "瞬态保留比例",
    "highpass_delta_hz": "高通偏移 · Hz",
    "sibilance_delta_db": "齿音频带偏移 · dB",
}

STAGE_TITLES = {"denoise": "降噪", "compress": "压缩", "eq": "均衡", "deess": "齿音控制"}


class SegmentModel(QAbstractTableModel):
    headings = ("开始", "结束", "段落", "推测类型", "证据强度")

    def __init__(self, parts, parent):
        super().__init__(parent)
        self.parts = parts

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.parts)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headings)

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headings[section]
        return super().headerData(section, orientation, role)

    def data(self, index, role):
        if role == Qt.DisplayRole and index.isValid():
            p = self.parts[index.row()]
            confidence = p.get("confidence")
            return (
                timecode(p["start"]),
                timecode(p["end"]),
                p.get("label", "手动段"),
                p.get("type", "—"),
                f"{confidence:.0%}" if confidence is not None else "—",
            )[index.column()]


def segment_table(parts, parent):
    table = QTableView()
    table.setModel(SegmentModel(parts, table))
    table.setSelectionBehavior(QTableView.SelectRows)
    table.setSelectionMode(QTableView.SingleSelection)
    table.verticalHeader().hide()
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    return table


class AutomationPage(QWidget):
    def __init__(self, controls, parts):
        super().__init__()
        self.controls = deepcopy(controls)
        self.initial = deepcopy(controls)
        self.row = None
        layout = QVBoxLayout(self)
        by_time = {(r["start"], r["end"]): r for r in parts}
        self.table = segment_table(
            [dict(by_time.get((c["start"], c["end"]), {}), **c) for c in controls], self
        )
        layout.addWidget(self.table)
        self.inputs = {}
        form = QFormLayout()
        layout.addLayout(form)
        for key, name in FIELDS.items():
            box = QDoubleSpinBox()
            lo, hi, _ = CONTROLS[key]
            box.setRange(lo, hi)
            box.setSingleStep(1.0 if key == "highpass_delta_hz" else 0.05)
            box.valueChanged.connect(lambda v, k=key: self.changed(k, v))
            self.inputs[key] = box
            form.addRow(name, box)
        reset = QPushButton("还原所选段进入编辑器时的参数")
        reset.clicked.connect(self.restore)
        layout.addWidget(reset)
        self.table.selectionModel().currentRowChanged.connect(lambda cur, old: self.select(cur.row()))
        if controls:
            self.table.selectRow(0)

    def changed(self, key, value):
        if self.row is not None:
            self.controls[self.row][key] = value

    def select(self, index):
        if index < 0:
            return
        self.row = index
        for key, box in self.inputs.items():
            box.blockSignals(True)
            box.setValue(self.controls[index].get(key, CONTROLS[key][2]))
            box.blockSignals(False)

    def restore(self):
        if self.row is not None:
            self.controls[self.row] = deepcopy(self.initial[self.row])
            self.select(self.row)


def audit_text(session):
    audit = session.audit
    before, after = session.analysis, session.measured
    if not after:
        return "渲染后可查看处理前后对照。"
    stages = {
        "denoise": "降噪",
        "eq": "EQ",
        "compress": "压缩",
        "deess": "齿音控制",
        "pitch": "音高",
        "space": "空间",
        "master": "母带",
        "stereo": "宽度",
        "saturate": "饱和",
    }
    lines = [
        "实测产生采样变化的处理环节",
        " / ".join(stages.get(k, k) for k in audit.get("changed_stages", [])) or "未记录人声效果变化",
        "",
        "原音 → 最终总线",
    ]
    for key, title, unit in [
        ("lufs", "综合响度", "LUFS"),
        ("short_term_max_lufs", "最高 3 秒响度", "LUFS"),
        ("true_peak_db", "真峰值", "dBTP"),
        ("rms_db", "RMS", "dBFS"),
        ("crest_db", "峰均比", "dB"),
        ("dynamic_db", "活动帧动态", "dB"),
        ("noise_db", "安静帧电平估计", "dBFS"),
        ("stereo_correlation", "左右声道相关系数", ""),
    ]:
        a, b = before.get(key), after.get(key)
        lines.append(
            f"{title}    {a:.2f} → {b:.2f} {unit}"
            if a is not None and b is not None
            else f"{title}    证据不足"
        )
    lines.extend(["", "频谱对照 · 各频带占总功率 dB"])
    for key, a in before["bands_db"].items():
        lines.append(f"{key:12}    {a:.1f} → {after['bands_db'][key]:.1f}")
    if "denoise" in audit:
        n = audit["denoise"]
        lines += [
            "",
            f"降噪阶段 · 同一组安静窗前后 {n['quiet_before_db']:.1f} → {n['quiet_after_db']:.1f} dBFS。",
        ]
    if "compression" in audit:
        c = audit["compression"]
        lines += [
            f"压缩器实测最大衰减 {c['max_gr_db']:.1f} dB，第 95 百分位 {c['p95_gr_db']:.1f} dB。"
        ]
    if "peak_trim_db" in audit:
        lines.append(f"复测后总线增益修正 {audit['peak_trim_db']:+.2f} dB。")
    if song := audit.get("song"):
        plan, premaster = song["plan"], song["before_master"]
        lines.extend(["", "歌曲工作流 · 原始分轨 → 混音总线 → 母带"])
        lines.append(
            f"人声 {song['stems']['Vocal']['lufs']:.1f} LUFS，"
            f"伴奏 {song['stems']['Instrumental']['lufs']:.1f} LUFS（两轨处理前）。"
        )
        lines.append(
            f"混音总线 → 成品：{premaster['lufs']:.1f} → {after['lufs']:.1f} LUFS，"
            f"{premaster['true_peak_db']:.1f} → {after['true_peak_db']:.1f} dBTP。"
        )
        lines.append(f"母带目标 {plan['target_lufs']:.1f} LUFS；峰值上限 {plan['ceiling_db']:.1f} dBTP。")
    if separation := getattr(session, "document", {}).get("separation"):
        providers = separation.get("providers", [])
        if separation.get("status") != "verified":
            lines.append("分离来源未验证或媒体已替换：无可复用的模型、后端或重建结论。")
        elif isinstance(providers, list) and all(isinstance(p, str) for p in providers):
            lines.append("分离推理后端：" + (" / ".join(providers) or "未知"))
        lines.append("分轨的重建误差不代表泄漏或分离伪影，请以实际试听判断。")
    return "\n".join(
        lines
        + [
            "",
            "复测提示",
            *(audit.get("output_warnings") or ["未触发电平、长度、声道或非有限值异常。"]),
        ]
    )


class TracePlot(QWidget):
    """Plot measured points on a common dB scale, with time or band labels."""

    def __init__(self, series, ticks):
        super().__init__()
        self.series = series
        self.ticks = ticks
        self.setMinimumHeight(95)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#141b25"))
        left, top = 42, 10
        width, height = max(1, self.width() - 90), max(1, self.height() - 42)
        low = min(-3.0, float(np.floor(min(min(y) for y in self.series))))
        for value in (0, low / 2, low):
            y = int(top + height * value / low)
            painter.setPen(QColor("#334052"))
            painter.drawLine(left, y, left + width, y)
            painter.setPen(QColor("#a2b3c8"))
            painter.drawText(5, y + 4, f"{value:.0f}")
        for i, tick in enumerate(self.ticks):
            x = left + width * i / max(1, len(self.ticks) - 1)
            painter.drawText(
                int(x - painter.fontMetrics().horizontalAdvance(tick) / 2), top + height + 19, tick
            )
        colors = ("#49c6b7",) if len(self.series) == 1 else ("#98a9be", "#49c6b7")
        for series, color in zip(self.series, colors):
            painter.setPen(QPen(QColor(color), 2))
            points = QPolygonF(
                [
                    QPointF(left + width * i / max(1, len(series) - 1), top + height * v / low)
                    for i, v in enumerate(series)
                ]
            )
            if len(points) == 1:
                painter.drawPoint(points[0])
            else:
                painter.drawPolyline(points)


class ReportDialog(QDialog):
    def __init__(self, session, report, summary, parent):
        super().__init__(parent)
        self.interval = None
        self.stage = None
        self.setWindowTitle("音频体检与处理复测")
        self.resize(740, 590)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        def text_tab(title, content):
            text = QPlainTextEdit()
            text.setPlainText(content)
            text.setReadOnly(True)
            tabs.addTab(text, title)

        text_tab("音频体检", summary)
        parts = report.get("segments", [])
        page = QWidget()
        col = QVBoxLayout(page)
        table = segment_table(parts, self)
        col.addWidget(table)
        evidence = QLabel()
        evidence.setWordWrap(True)
        col.addWidget(evidence)

        def choose(i, _):
            if i.isValid():
                row = parts[i.row()]
                self.interval = (row["start"], row["end"])
                evidence.setText("\n".join(row["evidence"] + row["limitations"]))

        table.selectionModel().currentRowChanged.connect(choose)
        listen = QPushButton("试听所选区间")
        listen.setEnabled(bool(parts))
        listen.clicked.connect(self.accept)
        col.addWidget(listen)
        if parts:
            table.selectRow(0)
        tabs.addTab(page, "时间分段")
        text_tab("处理前后", audit_text(session))
        if session.measured:
            curve = session.audit.get("compression", {}).get("curve", [])
            plots = QWidget()
            column = QVBoxLayout(plots)
            eq = session.audit.get("eq", {})
            bands = eq.get("before_bands_db", {})
            if bands:
                keys = list(bands)
                column.addWidget(QLabel("均衡器输入与输出 · 各频带相对功率（dB）"))
                column.addWidget(
                    TracePlot([list(bands.values()), [eq["after_bands_db"][k] for k in keys]], keys)
                )
                column.addWidget(QLabel("灰蓝为输入，青色为输出"))
            if curve:
                column.addWidget(QLabel("压缩器增益衰减（dB）"))
                column.addWidget(
                    TracePlot(
                        [[-point[1] for point in curve]],
                        [timecode(curve[0][0]), timecode(curve[-1][0])],
                    )
                )
            stage_choice = QComboBox()
            for key, label in STAGE_TITLES.items():
                if key in session.audit.get("stages", []):
                    stage_choice.addItem(label, key)
            if stage_choice.count():
                column.addWidget(stage_choice)
                play = QPushButton("等响试听此模块前后 · 使用时间轴选区或播放位置")

                def audition():
                    self.stage = stage_choice.currentData()
                    self.accept()

                play.clicked.connect(audition)
                column.addWidget(play)
            else:
                column.addWidget(QLabel("本次未运行可比较的人声模块。"))
            tabs.addTab(plots, "效果器实测")
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class PreviewDialog(QDialog):
    def __init__(self, pair, levels, sr, device, volume, parent, stage=None):
        super().__init__(parent)
        self.setWindowTitle(STAGE_TITLES.get(stage, "参考匹配") + " · 等响区间试听")
        self.player = Playback()
        self.player.device = device
        self.side = 0
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        description = QLabel(
            f"区间 {len(pair[0]) / sr:.2f} 秒     A {levels[0]:.1f} / B {levels[1]:.1f} LUFS"
        )
        layout.addWidget(description)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.status = QLabel()
        names = ("A  模块输入", "B  模块输出") if stage else ("A  同风格原参数", "B  加入参考匹配")
        for side, title in enumerate(names):
            btn = QPushButton(title)
            btn.clicked.connect(lambda _, i=side: play(i))
            row.addWidget(btn)

        def play(i):
            pos = self.player.position if self.player.playing else 0
            self.player.stop()
            self.player.volume = volume * 10 ** ((min(levels) - levels[i]) / 20)
            try:
                self.player.play(pair[i], sr, start=pos, loop=True)
                self.status.setText("循环试听 · " + names[i])
            except Exception as exc:
                self.status.setText(str(exc))

        layout.addWidget(self.status)
        stop = QPushButton("停止")
        stop.clicked.connect(lambda: (self.player.stop(), self.status.setText("已停止")))
        layout.addWidget(stop)
        self.finished.connect(lambda _: self.player.stop())
