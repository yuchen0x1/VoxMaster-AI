"""Opt-in official updates. Work stays open until the user chooses to install."""
import time

from packaging.version import Version
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QTextBrowser, QVBoxLayout)

from . import __version__, updating
from .jobs import Worker


class UpdateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('VoxMaster AI · 官方更新')
        self.resize(620, 450)
        self.job = None
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
        self.action.setEnabled(False)
        self.job = Worker(task, self)
        self.job.progress.connect(self.on_progress)
        self.job.succeeded.connect(complete)
        self.job.failed.connect(self.failure)
        self.job.finished.connect(lambda: self.action.setEnabled(True))
        self.job.start()

    def on_progress(self, value, message):
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
            self.run(lambda ev, pg: updating.download(asset, ev, pg), self.downloaded)
        else:
            self.status.setText('正在校验官方版本与 Ed25519 签名…')
            self.run(lambda ev, pg: updating.check_release(), self.checked)

    def checked(self, data):
        self.notes.setPlainText(data['notes'])
        if Version(data['version']) <= Version(__version__):
            self.status.setText('已是最新版本 ' + __version__)
            return
        self.release = data
        self.status.setText('新版本 ' + data['version'] + ' · ' + data['published_at'])
        self.action.setText('下载并校验更新')

    def downloaded(self, path):
        self.package = path
        self.progress.setValue(100)
        self.status.setText('签名清单、下载大小与 SHA-256 均已校验。保存工程后可启动安装器。')
        self.action.setText('启动已验证的安装器')

    def failure(self, text):
        self.status.setText('更新失败：' + text)

    def reject(self):
        if self.job and self.job.isRunning():
            self.job.cancel.set()
            self.status.setText('正在取消，请等待当前网络请求结束后关闭。')
            return
        super().reject()

    def closeEvent(self, event):
        if self.job and self.job.isRunning():
            self.job.cancel.set()
            event.ignore()
        else:
            event.accept()
