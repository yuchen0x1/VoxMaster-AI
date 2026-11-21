"""Opt-in official updates. Work stays open until the user chooses to install."""
import time

from packaging.version import Version
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QTextBrowser, QVBoxLayout)

from . import __version__, updating
from .jobs import PublishedFile, Worker


class UpdateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('VoxMaster AI · 官方更新')
        self.resize(620, 450)
        self.job = None
        self.close_pending = False
        self.release = None
        self.package = None
        layout = QVBoxLayout(self)
        self.status = QLabel('当前版本 ' + __version__ + '。检查将连接 GitHub 官方发布页。')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(False)
        layout.addWidget(self.notes)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.action = QPushButton('检查官方更新')
        self.action.clicked.connect(self.act)
        layout.addWidget(self.action)
        details = QPushButton('查看官方发布页')
        details.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(updating.RELEASES)))
        layout.addWidget(details)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def run(self, task, complete):
        if self.job is not None:
            return
        self.action.setEnabled(False)
        self.job = Worker(task, self)
        self.job.progress.connect(self.on_progress)
        self.job.succeeded.connect(lambda result: self.completed(complete, result))
        self.job.failed.connect(self.failure)
        self.job.cancelled.connect(self.cancelled)
        self.job.finished.connect(self.job_finished)
        self.job.start()

    def completed(self, complete, result):
        if not self.close_pending or isinstance(result, PublishedFile):
            complete(result)

    def cancelled(self):
        self.status.setText('更新已取消。')

    def job_finished(self):
        job = self.job
        self.job = None
        if job:
            job.deleteLater()
        self.action.setEnabled(True)
        if self.close_pending:
            self.reject()

    def on_progress(self, value, message):
        if self.close_pending:
            return
        self.progress.setValue(int(value * 100))
        elapsed = max(.01, time.monotonic() - self.started)
        size = updating.installer_asset(self.release)['size']
        self.status.setText(message + f' · 平均 {size * value / elapsed / 1024:.0f} KiB/s')

    def act(self):
        if self.package:
            parent = self.parent()
            if parent and getattr(parent, 'worker', None):
                self.status.setText('请等待音频任务完成，再安装更新。')
                return
            answer = QMessageBox.question(self, '安装更新',
                '请先保存工程。安装器会提示关闭正在运行的软件，完成后可重新启动。继续？')
            if answer == QMessageBox.Yes:
                try:
                    updating.launch_installer(self.package, self.release)
                    self.accept()
                except Exception as exc:
                    self.failure(str(exc))
        elif self.release:
            try:
                asset = updating.installer_asset(self.release)
            except (KeyError, ValueError) as exc:
                self.failure(str(exc))
                return
            self.started = time.monotonic()
            self.run(lambda ev, pg: PublishedFile(updating.download(asset, ev, pg)),
                     lambda receipt: self.downloaded(receipt.path))
        else:
            self.status.setText('正在校验官方版本与 Ed25519 签名…')
            self.run(self.check, self.checked)

    @staticmethod
    def check(cancel, _progress):
        data = updating.check_release(cancel)
        if Version(data['version']) > Version(__version__):
            try:
                asset = updating.installer_asset(data)
            except (KeyError, ValueError):
                pass  # The GUI shows the existing unsupported-platform or missing-asset message.
            else:
                return data, updating.cached_installer(asset, cancel)
        return data, None

    def checked(self, result):
        data, cached = result
        self.notes.setPlainText(data['notes'])
        if Version(data['version']) <= Version(__version__):
            self.status.setText('已是最新版本 ' + __version__)
            return
        self.release = data
        if cached is not None:
            self.downloaded(cached)
            return
        # Trust transparency: show what will be downloaded before asking to continue.
        try:
            asset = updating.installer_asset(data)
            size = f"安装包 {asset['size'] / 1024 / 1024:.1f} MiB · SHA-256 {asset['sha256'][:16]}…"
        except (KeyError, ValueError) as exc:
            size = str(exc)
        self.status.setText('新版本 ' + data['version'] + ' · ' + data['published_at']
                            + (' · ' + size if size else ''))
        self.action.setText('下载并校验更新')

    def downloaded(self, path):
        self.package = path
        self.progress.setValue(100)
        self.status.setText('签名清单、安装包大小与 SHA-256 均已校验。保存工程后可启动安装器。')
        self.action.setText('启动已验证的安装器')

    def failure(self, text):
        self.status.setText('更新失败：' + text)

    def reject(self):
        if self.job is not None:
            self.close_pending = True
            self.job.cancel.set()
            self.status.setText('正在取消，请等待当前更新任务结束后关闭。')
            return
        self.close_pending = False
        super().reject()

    def closeEvent(self, event):
        if self.job is not None:
            self.reject()
            event.ignore()
        else:
            event.accept()
