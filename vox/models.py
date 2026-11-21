"""Optional model center and public source-separation API."""

from __future__ import annotations

import json
import threading
import time
import urllib.request

from PySide6.QtCore import QThread, Signal, Slot
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


_UPSTREAM_SOCKET_TIMEOUT = 3
_UPSTREAM_DEADLINE = 15
_UPSTREAM_MAX_BYTES = 1024 * 1024
# A modal dialog (or its parent) can be deleted independently of a blocked
# request. Retain unparented QThreads until finished, never until merely stopped.
_RUNNING_TASKS = set()


class ModelTask(QThread):
    update = Signal(float, str)
    result = Signal(str)

    def __init__(self, task, parent=None, *, download=False):
        super().__init__()
        self.task = task
        self.stop = threading.Event()
        self.download = download
        self.discard = False
        self.cancel_message = None
        if parent is not None:
            parent.destroyed.connect(self.request_stop)

    def start(self, *args, **kwargs):
        # Connect disposal after the caller's finished slot: otherwise a fast
        # worker can delete its sender before the dialog clears its task handle.
        self.finished.connect(self._release)
        _RUNNING_TASKS.add(self)
        try:
            super().start(*args, **kwargs)
        except Exception:
            if not self.isRunning():
                _RUNNING_TASKS.discard(self)
            raise

    @Slot()
    def request_stop(self):
        self.stop.set()

    @Slot()
    def _release(self):
        _RUNNING_TASKS.discard(self)
        self.task = None
        self.deleteLater()

    def run(self):
        try:
            store.check_cancel(self.stop)
            msg = self.task(self.stop, self.update.emit)
            self.result.emit(msg or "已完成")
        except InterruptedError:
            if self.download and self.discard:
                try:
                    store.remove(partial=True)
                    self.cancel_message = "下载已取消"
                except (OSError, RuntimeError) as err:
                    self.cancel_message = "下载已取消，清理未完成 · " + str(err)
            elif self.download:
                self.cancel_message = "任务已暂停，可继续下载"
            else:
                self.cancel_message = "任务已取消"
            self.result.emit(self.cancel_message)
        except Exception as exc:
            self.result.emit("操作未完成 · " + (str(exc) or type(exc).__name__))


class ModelDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 模型中心")
        self.resize(660, 440)
        self.task = None
        self.close_pending = False
        self._close_result = QDialog.Rejected
        self._stop_requested = None
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
        self.cancel.setText("取消下载")
        self.cancel.setEnabled(partial)
        self.pause.setEnabled(False)

    def _restore_controls(self):
        for button in (self.start, self.migrate, self.update):
            button.setEnabled(True)
        for button in (self.pause, self.cancel, self.check, self.delete):
            button.setEnabled(False)
        self.cancel.setText("取消下载")
        try:
            self.refresh()
        except (OSError, RuntimeError) as exc:
            if not self.close_pending:
                self.message.setText("无法读取模型状态 · " + str(exc))

    def _run(self, action, download=False):
        if self.task is not None or self.close_pending:
            return
        for button in (self.start, self.migrate, self.update, self.check, self.delete):
            button.setEnabled(False)
        self.pause.setEnabled(download)
        self.cancel.setText("取消下载" if download else "取消任务")
        self.cancel.setEnabled(True)
        self._stop_requested = None
        self.message.setText("正在处理…")
        task = None
        try:
            task = ModelTask(action, self, download=download)
            self.task = task
            task.update.connect(self._progress)
            task.result.connect(self._result)
            task.finished.connect(self._finished)
            task.start()
        except Exception as exc:
            text = "任务无法启动 · " + (str(exc) or type(exc).__name__)
            if task is not None and task.isRunning():
                # A startup hook can fail after starting the native thread.
                # Keep it alive and busy until its real finished signal arrives.
                self._request_stop()
                self.message.setText(text + "；已请求取消，请等待当前任务结束。")
            else:
                self.task = None
                if task is not None:
                    task.deleteLater()
                self._restore_controls()
                self.message.setText(text)

    @Slot()
    def _finished(self):
        task = self.sender()
        if task is None or task is not self.task:
            return
        self.task = None
        if self._stop_requested and not self.close_pending:
            text = task.cancel_message
            if not text:
                # Cancel can win the GUI race after success was already queued.
                # Do not claim a completed file operation was rolled back.
                text = (
                    "任务已结束，已保留下载数据"
                    if self._stop_requested == "pause"
                    else "任务已结束（已请求取消），请确认模型状态"
                )
            self.message.setText(text)
        self._stop_requested = None
        self._restore_controls()
        if self.close_pending:
            self.done(self._close_result)

    def _accepts_result(self):
        return (
            self.task is not None
            and self.sender() is self.task
            and not self._stop_requested
            and not self.close_pending
        )

    @Slot(str)
    def _result(self, message):
        if self._accepts_result():
            self.message.setText(message)

    @Slot(float, str)
    def _progress(self, fraction, message):
        if self._accepts_result():
            self.progress.setValue(int(1000 * fraction))
            self.message.setText(message)

    def _download(self):
        root = store.directory()
        force = all(store.size_of(root / n) == size for n, (size, _) in store.FILES.items())
        self._run(lambda c, p: store.install(c, p, force), download=True)

    def _request_stop(self, *, pause=False, discard=False):
        if self.task is None:
            return
        self._stop_requested = "pause" if pause else "cancel"
        if discard and self.task.download:
            self.task.discard = True
        self.task.stop.set()
        self.pause.setEnabled(False)
        self.cancel.setEnabled(False)
        if self.close_pending:
            text = "已请求关闭，正在取消任务；请等待当前网络请求或文件操作结束。"
        elif pause:
            text = "已请求暂停，请等待当前网络请求或文件操作结束。"
        else:
            text = "已请求取消，请等待当前网络请求或文件操作结束。"
        self.message.setText(text)

    def _pause(self):
        if self.task is not None and self.task.download:
            self._request_stop(pause=True)

    def _cancel(self):
        if self.task is not None:
            self._request_stop(discard=True)
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
        deadline = time.monotonic() + _UPSTREAM_DEADLINE

        def checkpoint():
            store.check_cancel(cancel)
            if time.monotonic() >= deadline:
                raise TimeoutError("检查上游版本超时，请稍后重试。")

        checkpoint()
        url = "https://huggingface.co/api/models/" + store.REPOSITORY
        # urllib's timeout is a socket-idle limit, not a whole-request deadline.
        # A current socket call may still take this long to return; DNS and HTTP
        # header parsing are controlled by urllib/the OS, not these checkpoints.
        socket_timeout = min(
            _UPSTREAM_SOCKET_TIMEOUT, max(0.001, deadline - time.monotonic())
        )
        with urllib.request.urlopen(url, timeout=socket_timeout) as response:
            checkpoint()
            read = getattr(response, "read1", None)
            # HTTPResponse.read(n) fills n bytes and can wait forever on trickle.
            # read1 performs at most one buffered/raw read. For other file-like
            # responses, a one-byte read avoids the fill loop as well.
            block_size = 64 * 1024 if callable(read) else 1
            if not callable(read):
                read = response.read
            body = bytearray()
            while True:
                checkpoint()
                block = read(min(block_size, _UPSTREAM_MAX_BYTES - len(body) + 1))
                checkpoint()
                if not block:
                    break
                body.extend(block)
                if len(body) > _UPSTREAM_MAX_BYTES:
                    raise ValueError("上游版本响应大小超过上限")
        checkpoint()
        rev = json.loads(body)["sha"]
        checkpoint()
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

    def done(self, result):
        if self.task is not None:
            self.close_pending = True
            self._close_result = result
            self._request_stop()
            return
        self.close_pending = False
        super().done(result)

    def accept(self):
        self.done(QDialog.Accepted)

    def reject(self):
        self.done(QDialog.Rejected)

    def closeEvent(self, event):
        if self.task is not None:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
