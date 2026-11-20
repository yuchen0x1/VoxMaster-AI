"""Native guided setup and exact controls for a resolved full-song plan."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .song import MASTERING, TARGETS, _LIMITS, validate_plan


FIELDS = {
    "vocal_gain_db": ("人声电平", " dB"),
    "instrumental_gain_db": ("伴奏电平", " dB"),
    "instrumental_low_db": ("伴奏低频", " dB"),
    "instrumental_mid_db": ("伴奏中频", " dB"),
    "instrumental_high_db": ("伴奏高频", " dB"),
    "target_lufs": ("母带响度目标", " LUFS"),
    "ceiling_db": ("母带真峰值上限", " dBTP"),
}


class SongDialog(QDialog):
    def __init__(self, styles, style, *, has_stems, plan=None, recommend=False,
                 replaces_vocal=False, has_studio=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("整曲处理")
        self.setMinimumWidth(420)
        self.plan = validate_plan(plan) if plan is not None else None
        self.reviewing = self.plan is not None and not recommend
        self.recommend_again = False
        self.style_name = style
        self.values = {}
        layout = QVBoxLayout(self)
        content = QWidget()
        body = QVBoxLayout(content)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAccessibleName("整曲处理方案")
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        form = QFormLayout()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        apply = buttons.button(QDialogButtonBox.Ok)
        apply.setObjectName("songApply")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        if self.reviewing:
            text = (
                f"当前方案 · {TARGETS[self.plan['target']]} / {MASTERING[self.plan['master']]}\n"
                "可手动精确调整已生成的数值。混音项调整会标记为自定义；调整母带响度目标或真峰值上限不会改变所选母带力度。"
                "现有人声效果器参数会保留；母带作用于混音总线之后。"
            )
            for key, (caption, unit) in FIELDS.items():
                field = QDoubleSpinBox()
                field.setObjectName(key)
                field.setAccessibleName(caption)
                field.setRange(*_LIMITS[key][:2])
                field.setDecimals(3)
                field.setSingleStep(0.1)
                field.setSuffix(unit)
                field.setValue(self.plan[key])
                self.values[key] = field
                form.addRow(caption, field)
            apply.setText("应用并渲染")
            again = buttons.addButton("重新分析建议…", QDialogButtonBox.ActionRole)
            again.clicked.connect(self.request_recommendation)
        else:
            text = (
                "分析已就绪的人声与伴奏分轨，推荐相对电平、伴奏均衡及母带目标。"
                if has_stems else
                "先在本机分离人声与伴奏，再分析、混音并处理母带。"
                "分轨将保存到所选本地目录中的新子目录。"
            )
            text += "\n生成后可重新打开此对话框精确调整数值。"
            if replaces_vocal:
                text += "\n首次整曲分析将替换现有的人声调音参数，可撤销。"
            self.style_choice = QComboBox()
            self.style_choice.addItems(styles)
            self.style_choice.setCurrentText(style)
            # Recommending new mix/master values must not replace custom vocal parameters.
            self.style_choice.setEnabled(self.plan is None)
            form.addRow("人声风格", self.style_choice)
            self.target = self.profile(TARGETS, "target", "natural")
            self.master = self.profile(MASTERING, "master", "conservative")
            form.addRow("整曲目标", self.target)
            form.addRow("母带力度", self.master)
            apply.setText("分析并渲染" if has_stems else "分轨、分析并渲染")
        if has_studio:
            text += "\n保留多轨剪辑；整曲母带在多轨总线之后处理。"
        info = QLabel(text)
        info.setTextFormat(Qt.PlainText)
        info.setWordWrap(True)
        body.addWidget(info)
        body.addLayout(form)
        body.addStretch()
        layout.addWidget(buttons)
        # A fixed 540×560 left dead space below short plans; follow the content height.
        hint = self.sizeHint()
        available = self.screen().availableGeometry()
        self.resize(
            max(540, min(hint.width(), available.width() - 40)),
            max(self.minimumSizeHint().height(),
                min(hint.height(), available.height() - 60)),
        )

    def profile(self, labels, key, default):
        box = QComboBox()
        box.setObjectName(key)
        for value, caption in labels.items():
            if value != "custom":
                box.addItem(caption, value)
        selected = box.findData(self.plan[key]) if self.plan is not None else -1
        box.setCurrentIndex(selected if selected >= 0 else box.findData(default))
        return box

    def request_recommendation(self):
        self.recommend_again = True
        self.accept()

    def options(self):
        if not self.reviewing:
            return dict(style=self.style_choice.currentText(), target=self.target.currentData(),
                        master=self.master.currentData())
        plan = dict(self.plan)
        for key, field in self.values.items():
            value = field.value()
            if value != round(self.plan[key], field.decimals()):
                plan[key] = value
                if key not in ("target_lufs", "ceiling_db"):
                    plan["target"] = "custom"
        return dict(style=self.style_name, target=plan["target"], master=plan["master"], plan=plan)
