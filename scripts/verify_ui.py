"""Capture actual Qt renders using the licensed speech fixture, never private songs."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from vox import audioio, service, storage
from vox.interface import MainWindow
from vox.platforms import ui_font
from vox.song_dialog import SongDialog
from vox.studio import StudioDialog
from vox.update_dialog import UpdateDialog
from vox.visual import STYLES


def song_demo(folder):
    """Authorized real speech plus synthetic tones: UI evidence, not song quality acceptance."""
    folder.mkdir()
    vocal, _ = audioio.decode(ROOT / 'tests/fixtures/fleurs-mandarin.wav')
    level = service.engine.loudness(vocal, service.SR)
    vocal = vocal * np.float32(10 ** ((-24 - level) / 20))
    t = np.arange(len(vocal)) / service.SR
    music = (0.025 * np.column_stack((np.sin(2 * np.pi * 110 * t),
                                     np.sin(2 * np.pi * 165 * t)))).astype(np.float32)
    for name, data in [('Demo', vocal + music), ('Vocal', vocal), ('Instrumental', music)]:
        audioio.encode(folder / (name + '.wav'), data, service.SR, 32)
    document = storage.project(folder / 'Demo.wav', 'FLEURS + synthesized instrumental demo')
    document.update(mode='song', stems={role: str(folder / (role + '.wav'))
                                      for role in ('Vocal', 'Instrumental')})
    return document


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--song-demo', action='store_true', help='Also capture song plan and Studio')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setFont(QFont(ui_font(), 10))
    app.setStyleSheet(STYLES)
    window = MainWindow()
    window.show()
    window.open_path(str(ROOT / 'tests/fixtures/fleurs-mandarin.wav'))
    started = time.monotonic()
    state = {'phase': 'import', 'errors': [], 'song_demo': args.song_demo,
             'source': 'CC BY 4.0 FLEURS; optional instrumental is synthetic, not a real song'}
    window.notice = state['errors'].append

    def finish():
        (args.output / 'ui.json').write_text(json.dumps(state, indent=2), 'utf-8')
        window.close()
        app.exit(0 if not state['errors'] else 1)

    def step():
        if time.monotonic() - started > 180 or state['errors']:
            if time.monotonic() - started > 180:
                state['errors'].append('UI verification timed out')
            finish()
            return
        if window.worker or (getattr(window, 'hardware_job', None) and window.hardware_job.isRunning()):
            return
        if state['phase'] == 'import' and window.s:
            state['original_lufs'] = window.s.analysis['lufs']
            state['phase'] = 'render'
            window.go.click()
        elif state['phase'] == 'render' and window.s.output is not None:
            state['output_lufs'] = window.s.measured['lufs']
            window.grab().save(str(args.output / 'workstation.png'))
            dialog = UpdateDialog(window)
            dialog.show()
            app.processEvents()
            dialog.grab().save(str(args.output / 'official-update.png'))
            dialog.close()
            if not args.song_demo:
                state['phase'] = 'done'
                finish()
                return
            state['phase'] = 'song_import'
            document = song_demo(args.output / 'demo-sources')
            window.rebuild(document, '分析授权语音与合成伴奏演示', reset=True)
        elif state['phase'] == 'song_import':
            state['phase'] = 'song_render'
            current = window.s
            window.run_job('生成演示混音方案', lambda cancel, progress: service.plan_song(
                current, cancel, progress, target='natural', master='conservative'), window.commit_render)
        elif state['phase'] == 'song_render':
            state['phase'] = 'done'
            state['song_plan'] = window.s.document['song']
            window.grab().save(str(args.output / 'song-workstation.png'))
            review = SongDialog(list(service.engine.PRESETS), window.s.document['style'],
                                has_stems=True, plan=window.s.document['song'], parent=window)
            review.show()
            app.processEvents()
            review.grab().save(str(args.output / 'song-review.png'))
            review.close()
            studio = StudioDialog(window.s.mix_sources, service.SR, window)
            studio.show()
            app.processEvents()
            studio.grab().save(str(args.output / 'studio.png'))
            studio.close()
            finish()

    timer = QTimer()
    timer.timeout.connect(step)
    timer.start(250)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
