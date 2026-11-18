"""Keyboard-controlled, identity-blind A/B/C monitor for a local trial directory."""

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from vox.audioio import decode
from vox.playback import Playback


class ListeningPlayer(QDialog):
    def __init__(self, path):
        super().__init__()
        self.setWindowTitle("VoxMaster · 等响盲听")
        self.transport = Playback()
        self.clips = {}
        self.path = path
        self.selected = "A"
        self.setMinimumWidth(385)
        layout = QVBoxLayout(self)
        self.cases = QComboBox()
        candidates = [
            p.name for p in path.iterdir() if p.is_dir() and (p / "A.wav").is_file()
        ]
        if candidates:
            self.cases.addItems(sorted(candidates))
        elif (path / "A.wav").is_file():
            self.cases.addItem("当前试听")
        else:
            raise ValueError("目录中未找到盲听 A.wav")
        layout.addWidget(self.cases)
        chooser = QHBoxLayout()
        self.buttons = {}
        for label in "ABC":
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked, k=label: self.switch(k))
            chooser.addWidget(button)
            self.buttons[label] = button
            hotkey = QShortcut(QKeySequence(label), self)
            hotkey.activated.connect(lambda k=label: self.switch(k))
        layout.addLayout(chooser)
        self.status = QLabel()
        layout.addWidget(self.status)
        play = QPushButton("播放 / 暂停（空格）")
        play.clicked.connect(self.toggle)
        layout.addWidget(play)
        QShortcut(QKeySequence("Space"), self).activated.connect(self.toggle)
        self.cases.currentTextChanged.connect(self.load)
        self.load()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(100)

    def refresh(self):
        self.status.setText(
            f"{self.selected}   {self.transport.position:.1f} / {len(self.clips[self.selected]) / 44100:.1f} 秒"
        )

    def load(self, *_):
        self.transport.stop()
        path = (
            self.path
            if (self.path / "A.wav").is_file()
            else self.path / self.cases.currentText()
        )
        self.clips = {
            k: decode(path / (k + ".wav"))[0]
            for k in "ABC"
            if (path / (k + ".wav")).is_file()
        }
        for k, b in self.buttons.items():
            b.setEnabled(k in self.clips)
        self.switch("A")

    def switch(self, k):
        if k in self.clips:
            self.selected = k
            self.transport.replace_buffer(self.clips[k])
            for key, b in self.buttons.items():
                b.setChecked(key == k)
            self.refresh()

    def toggle(self):
        if self.transport.playing:
            self.transport.pause()
        else:
            x = self.clips[self.selected]
            at = self.transport.position
            self.transport.play(
                x, 44100, start=at if at < len(x) / 44100 - 0.03 else 0.0
            )

    def closeEvent(self, event):
        self.transport.close()
        super().closeEvent(event)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    args = p.parse_args()
    app = QApplication(sys.argv[:1])
    player = ListeningPlayer(args.directory)
    player.show()
    sys.exit(app.exec())
