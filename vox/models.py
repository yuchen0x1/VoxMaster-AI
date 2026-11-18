"""Optional model center and public source-separation API."""

from __future__ import annotations

import json
import threading
import urllib.request

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from . import models_store as store
from .models_runtime import providers, separate as separate


class ModelTask(QThread):
    update = Signal(float, str)
    result = Signal(str)

    def __init__(self, task, parent):
        super().__init__(parent)
        self.task = task
        self.stop = threading.Event()
        self.discard = False

    def run(self):
        try:
            msg = self.task(self.stop, self.update.emit)
            self.result.emit(msg or "已完成")
        except InterruptedError:
            if self.discard:
                try:
                    store.remove(partial=True)
                    self.result.emit("下载已取消")
                except OSError as err:
                    self.result.emit(str(err))
            else:
                self.result.emit("任务已暂停，可继续下载")
        except Exception as exc:
            self.result.emit("操作未完成 · " + str(exc))


class ModelDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 模型中心")
        self.resize(660, 440)
        self.task = None
        layout = QVBoxLayout(self)
        heading = QLabel("Spleeter 2-stem")
        heading.setStyleSheet("font-size:24px; font-weight:600")
        layout.addWidget(heading)
        layout.addWidget(QLabel("人声与伴奏分离    /    44.1 kHz · 双声道"))
        info = QFormLayout()
        layout.addLayout(info)
        self.state = QLabel()
        self.path = QLabel()
        self.path.setWordWrap(True)
        info.addRow(
            "版本", QLabel(f"ONNX FP32 · {store.REVISION[:8]} · {store.SIZE / 2**20:.1f} MiB")
        )
        info.addRow("模型状态", self.state)
        info.addRow("存储目录", self.path)
        self.mode = QComboBox()
        choices = [("自动选择", "auto"), ("CPU", "CPU")]
        available = providers("auto")
        if "DmlExecutionProvider" in available:
            choices.append(("DirectML 显卡（失败时回退 CPU）", "DirectML"))
        if "CUDAExecutionProvider" in available:
            choices.append(("NVIDIA CUDA（失败时回退 CPU）", "CUDA"))
        for label, value in choices:
            self.mode.addItem(label, value)
        self.mode.setCurrentIndex(max(0, self.mode.findData(store.settings().get("mode", "auto"))))
        self.mode.currentIndexChanged.connect(self._save_mode)
        info.addRow("运算设备", self.mode)
        terms = QLabel(
            "Deezer Spleeter · sherpa-onnx 转换。上游代码采用 MIT，权重的单独商业分发许可尚待作者确认。"
        )
        terms.setWordWrap(True)
        info.addRow("模型来源", terms)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.start = QPushButton("下载")
        self.pause = QPushButton("暂停")
        self.cancel = QPushButton("取消下载")
        self.check = QPushButton("校验")
        self.delete = QPushButton("删除")
        for button in (self.start, self.pause, self.cancel, self.check, self.delete):
            row.addWidget(button)
        self.start.clicked.connect(self._download)
        self.pause.clicked.connect(self._pause)
        self.cancel.clicked.connect(self._cancel)
        self.check.clicked.connect(lambda: self._run(self._verify))
        self.delete.clicked.connect(self._delete)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.migrate = QPushButton("更换存储位置")
        self.update = QPushButton("检查上游版本")
        self.details = QPushButton("模型详情")
        for button in (self.migrate, self.update, self.details):
            row.addWidget(button)
        self.migrate.clicked.connect(self._migrate)
        self.update.clicked.connect(lambda: self._run(self._upstream))
        self.details.clicked.connect(self._details)
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def _save_mode(self):
        try:
            store.save_settings(mode=self.mode.currentData())
        except (OSError, RuntimeError) as exc:
            self.message.setText(str(exc))

    def refresh(self):
        root = store.directory()
        good_sizes = all(store.size_of(root / n) == size for n, (size, _) in store.FILES.items())
        partial = any((root / (n + ".part")).exists() for n in store.FILES)
        if partial and good_sizes:
            count = sum(store.size_of(root / (n + ".part")) for n in store.FILES)
        else:
            count = sum(
                max(store.size_of(root / n), store.size_of(root / (n + ".part"))) for n in store.FILES
            )
        self.path.setText(str(root.parent))
        state = (
            "已安装 · 重新下载已暂停"
            if partial and good_sizes
            else "已安装 · 使用前自动校验"
            if good_sizes
            else "未完整下载"
            if count
            else "尚未下载"
        )
        self.state.setText(state)
        self.progress.setValue(int(1000 * count / store.SIZE))
        self.start.setText(
            "继续下载"
            if partial
            else "重新下载"
            if good_sizes
            else "继续下载"
            if count
            else "下载模型"
        )
        self.start.setEnabled(True)
        self.migrate.setEnabled(True)
        self.update.setEnabled(True)
        self.check.setEnabled(good_sizes)
        self.delete.setEnabled(count > 0)
        self.cancel.setEnabled(partial)
        self.pause.setEnabled(False)

    def _run(self, action, download=False):
        if self.task:
            return
        for button in (self.start, self.migrate, self.update, self.check, self.delete):
            button.setEnabled(False)
        self.pause.setEnabled(download)
        self.cancel.setEnabled(download)
        self.message.setText("正在处理…")
        self.task = ModelTask(action, self)
        self.task.update.connect(self._progress)
        self.task.result.connect(self.message.setText)
        self.task.finished.connect(self._finished)
        self.task.start()

    def _finished(self):
        self.task.deleteLater()
        self.task = None
        self.refresh()

    def _progress(self, fraction, message):
        self.progress.setValue(int(1000 * fraction))
        self.message.setText(message)

    def _download(self):
        root = store.directory()
        force = all(store.size_of(root / n) == size for n, (size, _) in store.FILES.items())
        self._run(lambda c, p: store.install(c, p, force), download=True)

    def _pause(self):
        if self.task:
            self.task.stop.set()
            self.message.setText("正在暂停传输…")

    def _cancel(self):
        if self.task:
            self.task.discard = True
            self.task.stop.set()
            self.message.setText("正在取消下载…")
        else:
            self._run(lambda c, p: store.remove(partial=True))

    @staticmethod
    def _verify(cancel, progress):
        store.verify(cancel=cancel)
        return "两个模型均已通过 SHA-256 校验"

    def _delete(self):
        if (
            QMessageBox.question(self, "删除模型", "删除下载的两个模型文件？可稍后重新下载。")
            == QMessageBox.Yes
        ):
            self._run(lambda c, p: store.remove())

    def _migrate(self):
        name = QFileDialog.getExistingDirectory(self, "选择新的模型存储目录")
        if name:
            self._run(lambda c, p: store.migrate(name, c))

    @staticmethod
    def _upstream(cancel, progress):
        url = "https://huggingface.co/api/models/" + store.REPOSITORY
        with urllib.request.urlopen(url, timeout=15) as r:
            rev = json.load(r)["sha"]
        return (
            "当前已是上游版本"
            if rev == store.REVISION
            else f"上游有新版 {rev[:8]} · 经兼容验证后将在软件更新中提供"
        )

    def _details(self):
        lines = [f"{k}\n{v[0]:,} 字节\nSHA-256 {v[1]}" for k, v in store.FILES.items()]
        QMessageBox.information(
            self,
            "模型详情",
            "\n\n".join(
                [
                    "用途：从歌曲或人声混音估计人声与伴奏两轨。",
                    "频谱上限约 11 kHz，更高频率保留在伴奏轨。\n内存与显存随运行库变化，分离时显示实测占用。",
                    "发布源：https://huggingface.co/" + store.REPOSITORY,
                    "固定版本：" + store.REVISION,
                    *lines,
                ]
            ),
        )

    def reject(self):
        if self.task:
            self.message.setText("任务执行中。下载可暂停后关闭此窗口。")
        else:
            super().reject()

    def closeEvent(self, event):
        if self.task:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
