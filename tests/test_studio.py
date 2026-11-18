import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np

from vox.audioio import decode, encode
from vox.studio_session import Session, load_sources


class SessionTests(unittest.TestCase):
    sr = 44100

    def setUp(self):
        n = 90003
        t = np.arange(n, dtype=np.float64) / self.sr
        self.vocal = np.stack((0.13 * np.sin(t * 1630), 0.07 * np.cos(t * 2351)), axis=1).astype(
            "float32"
        )
        self.beat = np.zeros_like(self.vocal)
        self.beat[[320, 65535, 65536], 0] = 0.4
        self.sources = {"Vocal": self.vocal, "Instrumental": self.beat}
        self.session = Session(self.sources, self.sr)

    def test_master_sync_mute_solo_and_pan(self):
        m = self.session
        np.testing.assert_allclose(m.render(), self.vocal + self.beat)
        m.set_param("Vocal", "mute", True)
        np.testing.assert_allclose(m.render(), self.beat)
        m.undo()
        m.set_param("Vocal", "solo", True)
        np.testing.assert_allclose(m.render(), self.vocal)
        m.set_param("Vocal", "pan", 1)
        out = m.render()
        np.testing.assert_allclose(out[:, 0], 0, atol=1e-7)
        np.testing.assert_allclose(out[:, 1], self.vocal.mean(axis=1) * np.sqrt(2), atol=1e-7)
        np.testing.assert_array_equal(m.render(track="Instrumental"), self.beat)

    def test_split_copy_paste_fade_envelope_undo_and_reopen(self):
        m = self.session
        self.assertTrue(m.point("Vocal", 10000, 0.3))
        self.assertTrue(m.split("Vocal", 65536))
        split = m.render()
        self.assertTrue(m.join("Vocal", 65536))
        np.testing.assert_allclose(split, m.render(), atol=1e-7)
        m.copy_region("Vocal", 0, 1000)
        m.paste("FX", 200)
        self.assertEqual(m.strip("FX")["clips"][0]["at"], 200)
        out = m.render().copy()
        m.fade("FX", 200, 1200, True)
        stem = m.render(track="FX")
        self.assertEqual(stem[200, 1], 0.0)
        self.assertGreater(abs(stem[1199, 0]), 0.0)
        restored = Session(self.sources, self.sr, json.loads(json.dumps(m.saved_state())))
        np.testing.assert_array_equal(restored.render(), m.render())
        m.undo()
        np.testing.assert_array_equal(out, m.render())
        m.undo(redo=True)
        np.testing.assert_array_equal(stem, m.render(track="FX"))
        m.replace("Vocal", 0, 9999, [])
        self.assertEqual(m.strip("Vocal")["clips"][0]["start"], 9999)

    def test_move_overlapping_one_undo_and_nonzero_gaps(self):
        m = self.session
        before = m.render()
        m.move("Vocal", 150, 250, 200)
        output = m.render(track="Vocal")
        np.testing.assert_array_equal(output[150:200], 0)
        np.testing.assert_array_equal(output[200:300], self.vocal[150:250])
        m.undo()
        np.testing.assert_array_equal(before, m.render())

    def test_filter_drive_cancellation_and_ceiling(self):
        m = self.session
        before = m.render()
        m.set_param("Vocal", "highpass", 220)
        m.set_param("Vocal", "drive", 1.3)
        self.assertGreater(float(np.mean(np.abs(before - m.render()))), 0.01)
        m.set_param("Vocal", "gain", 12)
        m.set_param(None, "master_db", 12)
        metrics = {}
        out = m.render(metrics=metrics)
        peak = float(np.abs(out).max())
        self.assertLessEqual(peak, 0.980001)
        self.assertGreater(metrics["reduction_db"], 1.0)
        self.assertAlmostEqual(metrics["peak_db"], 20 * np.log10(peak), places=5)
        self.assertAlmostEqual(
            metrics["pre_peak_db"] - metrics["reduction_db"], metrics["peak_db"], places=5
        )
        event = threading.Event()
        event.set()
        with self.assertRaises(InterruptedError):
            m.render(event)

    def test_mandarin_audio_export_restore_and_integrity(self):
        source = Path(__file__).parent / "fixtures" / "fleurs-mandarin.wav"
        self.assertTrue(source.exists(), "真实中文录音验收素材缺失")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        voice, meta = decode(source)
        session = Session({"Vocal": voice}, self.sr)
        end = min(len(voice), self.sr)
        session.copy_region("Vocal", 0, end)
        session.paste("FX", self.sr // 2)
        session.set_param("FX", "gain", -12.0)
        session.fade("FX", self.sr // 2, self.sr // 2 + end, False)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "效果轨.wav"
            stem = session.render(track="FX")
            encode(path, stem, self.sr, bitdepth=24)
            session.import_clip("Instrumental", "extra", path, decode(path)[0], 0)
            state = json.loads(json.dumps(session.saved_state()))
            restored = Session(load_sources(state, {"Vocal": voice}), self.sr, state)
            np.testing.assert_array_equal(session.render(), restored.render())
            difference = np.mean(np.abs(restored.render()[: len(voice)] - voice))
            self.assertGreater(difference, 0.000001)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
            wav, _ = decode(path)
            np.testing.assert_allclose(wav, stem, atol=4e-7)
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                load_sources(state, {"Vocal": voice})

    def test_invalid_state_refused(self):
        m = self.session.saved_state()
        m["tracks"]["Vocal"]["clips"][0]["at"] = 10**15
        with self.assertRaises(ValueError):
            Session(self.sources, self.sr, m)

    def test_saved_stems_and_added_accompaniment_render_once(self):
        from vox.service import prepare
        from vox.storage import load_project, project, save_project
        from vox.engine import recommend

        # Build known additive stems to test routing independently of separation quality.
        fixture = Path(__file__).parent / "fixtures" / "fleurs-mandarin.wav"
        voice = decode(fixture)[0][2 * self.sr : 4 * self.sr]
        beat = self.beat[: len(voice)] * 0.2
        event = threading.Event()

        def run(doc, previous=None):
            return prepare(doc, event, lambda *_: None, previous)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, dry, music, fx = [root / (n + ".wav") for n in ("mix", "vocal", "music", "fx")]
            for path, samples in (
                (source, voice + beat),
                (dry, voice),
                (music, beat),
                (fx, voice * 0.1),
            ):
                encode(path, samples, self.sr, bitdepth=32)
            doc = project(source)
            doc["stems"] = {"Vocal": str(dry), "Instrumental": str(music)}
            baseline = run(doc)
            doc["applied"] = True
            doc["params"] = recommend(baseline.vocal_report, "干净录音棚")
            tuned = run(doc, baseline)
            session = Session(dict(tuned.sources, Vocal=tuned.tuned_vocal), self.sr)
            session.set_param("Instrumental", "gain", -8.0)
            session.import_clip("FX", "added", fx, decode(fx)[0], 320)
            session.set_param("FX", "pan", -0.75)
            session.set_param(None, "master_db", -6.0)
            expected = session.render()
            doc["studio"] = session.saved_state()
            cached = run(doc, tuned)
            np.testing.assert_array_equal(cached.output, expected)
            file = root / "编排.voxproj"
            save_project(file, doc)
            reopened = run(load_project(file))
            np.testing.assert_array_equal(reopened.output, expected)
