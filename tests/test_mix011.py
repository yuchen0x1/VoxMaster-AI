import json
import threading
import time
import unittest
from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from vox.analysis import loudness
from vox.audioio import decode
from vox.studio import StudioDialog
from vox.studio_balance import measure
from vox.studio_effects import default_rack, default_routing
from vox.studio_mix_dialogs import BalanceDialog, RackDialog
from vox.studio_session import Session


SR = 44100


def stereo(x):
    return np.repeat(x[:, None], 2, axis=1).astype("float32")


def tone(f, seconds=3):
    return np.sin(2 * np.pi * f * np.arange(round(seconds * SR)) / SR)


class QualityMixTests(unittest.TestCase):
    def test_mono_monitor_is_independent_of_stereo_render(self):
        app = QApplication.instance() or QApplication([])
        x = 0.18 * tone(920, 1)
        stereo_source = np.column_stack((x, -x)).astype("float32")
        dialog = StudioDialog({"Vocal": stereo_source}, SR)

        def wait():
            until = time.monotonic() + 5
            while dialog.listen_mix is None and time.monotonic() < until:
                app.processEvents()
                time.sleep(0.008)
            self.assertIsNotNone(dialog.listen_mix)

        try:
            wait()
            dialog.mono.setChecked(True)
            wait()
            np.testing.assert_array_equal(dialog.listen_mix, 0)
            np.testing.assert_array_equal(dialog.render_mix(), stereo_source)
            dialog.mono.setChecked(False)
            wait()
            self.assertIs(dialog.listen_mix, dialog.cache)
        finally:
            dialog.reject()

    def test_balance_responds_to_levels_overlap_and_frequency(self):
        voice = stereo(0.1 * tone(1250))
        loud = Session({"Vocal": voice, "Instrumental": voice * 2}, SR)
        soft = Session({"Vocal": voice, "Instrumental": voice * 0.2}, SR)
        same = measure(loud)["recommendation"]
        weak = measure(soft)["recommendation"]
        distinct = measure(Session({"Vocal": voice, "Instrumental": stereo(0.1 * tone(210))}, SR))[
            "recommendation"
        ]
        self.assertLess(same["music_gain"], 0)
        loud.configure_balance(same["routing"], same["music_gain"])
        music = loud.render(track="Instrumental")[SR : 2 * SR]
        vocal = loud.render(track="Vocal")[SR : 2 * SR]
        contrast = 20 * np.log10(np.linalg.norm(vocal) / np.linalg.norm(music))
        self.assertAlmostEqual(contrast, 4.0, delta=0.5)
        self.assertGreater(weak["music_gain"], 2)
        self.assertGreater(same["routing"]["duck_db"], weak["routing"]["duck_db"])
        self.assertEqual(same["band"], [900, 1800])
        self.assertGreater(same["routing"]["mask_db"], distinct["routing"]["mask_db"] + 2)
        split = len(voice) // 2
        a = voice.copy()
        b = voice.copy()
        a[:split] = 0
        b[split:] = 0
        self.assertIsNone(measure(Session({"Vocal": a, "Instrumental": b}, SR))["recommendation"])

    def test_vocal_key_ducks_only_during_phrases_and_masks_selected_band(self):
        voice = stereo(0.3 * tone(220))
        voice[: SR // 2] = 0
        voice[2 * SR :] = 0
        music = stereo(0.12 * (tone(120) + tone(1600)))
        session = Session({"Vocal": voice, "Instrumental": music}, SR)
        cfg = {
            **default_routing(),
            "enabled": True,
            "duck_db": 5.0,
            "mask_db": 0.0,
            "frequency": 1600.0,
            "threshold": -35.0,
        }
        session.configure_balance(cfg, 0)
        stem = session.render(track="Instrumental")
        np.testing.assert_array_equal(stem[: SR // 3], music[: SR // 3])

        def rms(x):
            return float(np.sqrt(np.mean(x * x)))

        self.assertLess(rms(stem[SR : 2 * SR]) / rms(music[SR : 2 * SR]), 0.6)
        self.assertGreater(rms(stem[-SR // 4 :]) / rms(music[-SR // 4 :]), 0.98)
        cfg.update(duck_db=0.0, mask_db=6.0)
        session.configure_balance(cfg, 0)
        stem = session.render(track="Instrumental")

        def transfer(freq):
            weight = tone(freq, 1)
            return np.dot(stem[SR : 2 * SR, 0], weight) / np.dot(music[SR : 2 * SR, 0], weight)

        self.assertLess(transfer(1600), 0.52)
        self.assertGreater(transfer(120), 0.97)
        # Soloing/exporting the backing preserves the vocal key; muting the vocal disables it.
        session.set_param("Instrumental", "solo", True)
        np.testing.assert_allclose(session.render(), stem, atol=1e-7)
        session.set_param("Vocal", "mute", True)
        np.testing.assert_allclose(session.render(track="Instrumental"), music, atol=1e-7)

    def test_correlation_fold_down_lufs_and_center(self):
        r = 0.15 * tone(1000)
        sources = {
            "Vocal": np.column_stack((r, r * 0.25)).astype("float32"),
            "Instrumental": stereo(r),
        }
        anti = np.column_stack((r, -r)).astype("float32")
        report = measure(Session({"FX": anti}, SR))
        self.assertLess(report["tracks"]["FX"]["mono_db"], -90)
        self.assertAlmostEqual(report["tracks"]["FX"]["correlation"], -1)
        self.assertAlmostEqual(report["tracks"]["FX"]["lufs"], loudness(anti, SR), places=5)
        s = Session(sources, SR)
        s.configure_balance({**default_routing(), "enabled": True, "center": 1.0}, 0.0, 0.0)
        centered = s.render(track="Vocal")
        np.testing.assert_array_equal(centered[:, 0], centered[:, 1])
        np.testing.assert_allclose(centered[:, 0], sources["Vocal"].mean(axis=1), atol=1e-7)

    def test_rack_order_bypass_restore_undo_on_real_recording(self):
        source = decode(Path(__file__).parent / "fixtures" / "fleurs-mandarin.wav")[0][
            2 * SR : 4 * SR
        ]
        # Set a known vocal peak so the real recording exercises the compressor threshold.
        source = source * (0.78 / np.abs(source).max())
        s = Session({"Vocal": source}, SR)
        original = s.render()
        old = s.saved_state()
        old.pop("racks")
        old.pop("routing")
        np.testing.assert_array_equal(Session({"Vocal": source}, SR, old).render(), original)
        rack = {**default_rack(), "presence": 5.0, "compress": 7.0}
        s.set_rack("Vocal", rack)
        a = s.render()
        self.assertGreater(np.mean(abs(a - original)), 0.0001)
        rack["order"] = ["compress", "presence", "width"]
        s.set_rack("Vocal", rack)
        self.assertGreater(np.max(abs(s.render() - a)), 1e-6)
        s.undo()
        np.testing.assert_array_equal(s.render(), a)
        s.set_rack("Master", {**default_rack(), "presence": -4.0})
        processed = s.render()
        self.assertGreater(np.mean(abs(processed - a)), 0.0001)
        np.testing.assert_array_equal(
            Session(s.sources, SR, json.loads(json.dumps(s.saved_state()))).render(), processed
        )
        np.testing.assert_array_equal(s.render(track="Vocal"), a)
        bypass = {**rack, "bypass": ["presence", "compress", "width"]}
        s.set_rack("Master", bypass)
        s.set_rack("Vocal", bypass)
        np.testing.assert_array_equal(s.render(), original)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            measure(s, cancel)

    def test_native_actions_apply_and_undo_balance_racks_and_loudness(self):
        app = QApplication.instance() or QApplication([])
        x = stereo(0.1 * tone(1400))
        dialog = StudioDialog({"Vocal": x, "Instrumental": x * 2}, SR)
        try:

            def enter(button, kind, edit):
                seen = []
                timer = QTimer()

                def poll():
                    active = app.activeModalWidget()
                    if isinstance(active, kind):
                        seen.append(True)
                        edit(active)
                        active.accept()
                        timer.stop()

                timer.timeout.connect(poll)
                timer.start(15)
                button.click()
                until = time.monotonic() + 8
                while not seen and time.monotonic() < until:
                    app.processEvents()
                    time.sleep(0.008)
                timer.stop()
                self.assertTrue(seen)

            enter(dialog.balance_button, BalanceDialog, lambda _: None)
            self.assertTrue(dialog.state["routing"]["enabled"])
            self.assertLess(dialog.session.strip("Instrumental")["gain"], 0)
            dialog._undo(False)
            self.assertFalse(dialog.state["routing"]["enabled"])

            def configure(d):
                d.target.setCurrentIndex(d.target.findData("Master"))
                d.values["presence"].setValue(-4.0)
                d.order.setCurrentRow(0)
                d.move(1)

            enter(dialog.rack_button, RackDialog, configure)
            self.assertEqual(dialog.state["racks"]["Master"]["order"][1], "presence")

            def match(d):
                d.mode.setCurrentIndex(1)
                d.match_track.setCurrentIndex(d.match_track.findData("Vocal"))
                d.target.setValue(-20.0)

            enter(dialog.balance_button, BalanceDialog, match)
            self.assertAlmostEqual(
                loudness(dialog.session.render(track="Vocal"), SR), -20, places=4
            )
        finally:
            dialog.reject()
