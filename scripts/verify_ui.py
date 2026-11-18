"""Render the actual desktop and official updater; capture native Qt screenshots."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from vox.interface import MainWindow
from vox.platforms import ui_font
from vox.update_dialog import UpdateDialog
from vox.visual import STYLES


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setFont(QFont(ui_font(), 10))
    app.setStyleSheet(STYLES)
    window = MainWindow()
    window.show()
    window.open_path(str(ROOT / 'tests/fixtures/fleurs-mandarin.wav'))
    started = time.monotonic()
    state = {'phase': 'import'}
    def step():
        if time.monotonic() - started > 120:
            app.exit(2)
            return
        if window.worker or getattr(window, 'hardware_job', None) and window.hardware_job.isRunning():
            return
        if state['phase'] == 'import' and window.s:
            state['original_lufs'] = window.s.analysis['lufs']
            state['phase'] = 'render'
            window.go.click()
        elif state['phase'] == 'render' and window.s.output is not None:
            state['output_lufs'] = window.s.measured['lufs']
            state['phase'] = 'done'
            window.grab().save(str(args.output / 'workstation.png'))
            dialog = UpdateDialog(window)
            dialog.show()
            app.processEvents()
            dialog.grab().save(str(args.output / 'official-update.png'))
            dialog.close()
            (args.output / 'ui.json').write_text(json.dumps(state, indent=2), 'utf-8')
            window.close()
            app.quit()
    timer = QTimer()
    timer.timeout.connect(step)
    timer.start(250)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
