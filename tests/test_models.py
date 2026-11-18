import hashlib
import io
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy import signal

from vox import models_runtime as rt
from vox import models_store as store


class Response(io.BytesIO):
    def __init__(self, data, status, headers):
        super().__init__(data)
        self.status, self.headers = status, headers


class ModelStorageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        env = patch.dict(os.environ, VOXMASTER_DATA=str(self.folder / "config"))
        env.start()
        self.addCleanup(env.stop)
        self.payload = b"ONNX-fixture" * 100
        self.sha = hashlib.sha256(self.payload).hexdigest()
        manifest = patch.dict(store.FILES, {"vocals.onnx": (len(self.payload), self.sha)}, clear=True)
        manifest.start()
        self.addCleanup(manifest.stop)

    def _resume(self, supported):
        root = store.directory()
        root.mkdir(parents=True)
        part = root / "vocals.onnx.part"
        part.write_bytes(self.payload[:33])

        def request(req, timeout):
            self.assertEqual(req.headers["Range"], "bytes=33-")
            if supported:
                return Response(
                    self.payload[33:], 206, {"Content-Range": f"bytes 33-1199/{len(self.payload)}"}
                )
            return Response(self.payload, 200, {})

        with patch("urllib.request.urlopen", request):
            store.install(threading.Event(), lambda *args: None, root=root)
        store.verify(root)
        self.assertFalse(part.exists())
        return root

    def test_resume_and_migrate(self):
        root = self._resume(True)
        store.migrate(self.folder / "Disk2", threading.Event())
        store.verify()
        self.assertFalse((root / "vocals.onnx").exists())
        (store.directory() / "keep-me.txt").write_text("ok")
        store.remove()
        self.assertTrue((store.directory() / "keep-me.txt").is_file())

    def test_range_ignored(self):
        self._resume(False)

    def test_corruption_preserves_working_installation(self):
        root = self._resume(True)
        with patch(
            "urllib.request.urlopen",
            side_effect=lambda *a, **kw: Response(b"x" * len(self.payload), 200, {}),
        ):
            with patch("time.sleep"), self.assertRaisesRegex(ValueError, "SHA-256"):
                store.install(None, lambda *args: None, root=root, force=True)
        store.verify(root)

    def test_cancel_before_network(self):
        event = threading.Event()
        event.set()
        with patch("urllib.request.urlopen") as network, self.assertRaises(InterruptedError):
            store.install(event, lambda *args: None)
        network.assert_not_called()


class SeparationTests(unittest.TestCase):
    def test_gpu_load_failure_retries_block_on_cpu(self):
        audio = np.zeros((441, 2), dtype="f")
        reported = []

        class FailingGPU:
            def __init__(self, root, provider):
                self.provider = provider
                self.conn = self

            def result(self, cancel, kind):
                if self.provider.startswith("Dml"):
                    raise RuntimeError("driver unavailable")
                if kind == "ok":
                    return np.zeros((2, rt.FRAMES, rt.BINS), dtype="f"), ""

            def send(self, data):
                pass

            def close(self):
                pass

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(rt, "Worker", FailingGPU),
            patch.object(store, "verify"),
            patch.object(
                rt, "providers", return_value=["DmlExecutionProvider", "CPUExecutionProvider"]
            ),
        ):
            rt.separate(audio, 44100, root=Path(tmp), progress=lambda f, m: reported.append(m))
        self.assertIn("CPUExecutionProvider", reported[-1])
        self.assertIn("已回退", reported[-1])

    def test_block_alignment_and_edges(self):
        t = np.arange(rt.STRIDE + 3200) / 44100
        # A smooth edge avoids broadband leakage from truncating a sine mid-cycle.
        tone = 0.3 * np.sin(2 * np.pi * 370 * t) * signal.windows.tukey(len(t), alpha=0.02)
        audio = np.repeat(tone.astype("f")[:, None], 2, axis=1)
        out = []
        mask = np.ones((2, rt.FRAMES, rt.BINS), dtype="f")
        for pos in range(0, len(t), rt.STRIDE):
            out.append(rt._synthesize(rt._spectrum(audio, pos), mask, min(rt.STRIDE, len(t) - pos)))
        self.assertLess(np.max(np.abs(np.concatenate(out) - audio)), 0.0001)

    @unittest.skipUnless(
        os.getenv("VOX_MODEL_TEST_WEIGHTS"), "set VOX_MODEL_TEST_WEIGHTS for local neural inference"
    )
    def test_real_speech_with_known_instrumental(self):
        from vox.audioio import decode

        audio, _ = decode(Path(__file__).parent / "fixtures" / "fleurs-mandarin.wav")
        voice = audio[: 44100 * 8]
        voice = voice * (0.12 / np.sqrt(np.mean(voice**2)))
        t = np.arange(len(voice)) / 44100
        beat = 0.115 * np.sin(2 * np.pi * 110 * t) + 0.08 * np.sin(2 * np.pi * 165 * t)
        beat *= 0.35 + 0.65 * np.exp(-4 * (t % 0.5))
        backing = np.column_stack((beat, 0.8 * beat)).astype("f")
        mixture = voice + backing
        vocal, inst = rt.separate(
            mixture,
            44100,
            root=Path(os.environ["VOX_MODEL_TEST_WEIGHTS"]),
            mode=os.getenv("VOX_MODEL_TEST_MODE", "CPU"),
        )

        def sdr(target, estimate):
            return 10 * np.log10(np.sum(target**2) / np.sum((target - estimate) ** 2))

        improvement = sdr(voice, vocal) - sdr(voice, mixture)
        print(f"Voice SDR improvement {improvement:.2f} dB, backing SDR {sdr(backing, inst):.2f} dB")
        self.assertGreater(improvement, 3.0)
        self.assertLess(np.max(np.abs(vocal + inst - mixture)), 1e-6)

    @unittest.skipUnless(os.getenv("VOX_MODEL_TEST_WEIGHTS"), "local two-stem weights required")
    def test_recover_active_gpu_worker_exit(self):
        if "DmlExecutionProvider" not in rt.providers("DirectML"):
            self.skipTest("DirectML provider required")
        from vox.audioio import decode

        root = Path(os.environ["VOX_MODEL_TEST_WEIGHTS"])
        voice, _ = decode(Path(__file__).parent / "fixtures" / "fleurs-mandarin.wav")
        x = np.tile(voice, (2, 1))[: rt.STRIDE * 2 + 100]
        baseline, _ = rt.separate(x, 44100, root=root, mode="CPU")
        workers, events = [], []
        injected = False
        worker_type = rt.Worker

        def create(*args):
            worker = worker_type(*args)
            workers.append(worker)
            return worker

        def progress(f, message):
            nonlocal injected
            events.append(message)
            if not injected and 0 < f < 1 and message.startswith("DmlExecutionProvider"):
                # Force only this test's dedicated native worker to exit. The
                # next block must restart via CPU and preserve the timeline.
                workers[0].process.terminate()
                workers[0].process.join(5)
                injected = True

        with patch.object(rt, "Worker", create):
            actual, backing = rt.separate(x, 44100, root=root, mode="DirectML", progress=progress)
        self.assertIn("CPUExecutionProvider", events[-1])
        self.assertTrue(injected)
        self.assertIn("已回退", events[-1])
        self.assertLess(np.max(np.abs(actual - baseline)), 0.001)
        self.assertLess(np.max(np.abs(actual + backing - x)), 1e-6)
