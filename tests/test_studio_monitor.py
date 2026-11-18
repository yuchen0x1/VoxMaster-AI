import time
import unittest
from types import SimpleNamespace

import numpy as np
from PySide6.QtWidgets import QApplication, QWidget

from vox.studio import StudioDialog


class MonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate):
        start = time.monotonic()
        while not predicate():
            self.app.processEvents()
            time.sleep(0.01)
            if time.monotonic() - start > 6:
                self.fail("Timed out waiting for the master render")

    def test_device_volume_stale_render_peak_feedback_and_roundtrip(self):
        rate = 44100
        ramp = np.linspace(-0.4, 0.4, rate, dtype=np.float32)
        sources = {
            "Vocal": np.stack([ramp, np.zeros_like(ramp)], axis=1),
            "Instrumental": np.column_stack((ramp, ramp)),
        }
        parent = QWidget()
        parent.player = SimpleNamespace(device=1, volume=0.17)
        dialog = StudioDialog(sources, rate, parent)
        try:
            self.assertEqual(dialog.player.device, 1)
            self.assertEqual(dialog.player.volume, 0.17)
            self.wait_for(lambda: dialog.cache is not None)
            np.testing.assert_allclose(
                dialog.wave.master_audio, sources["Vocal"] + sources["Instrumental"]
            )
            dialog.controls["Vocal"]["pan"].setValue(1)
            dialog.controls["Instrumental"]["mute"].setChecked(True)
            dialog.master.setValue(12)
            self.wait_for(lambda: dialog.cache is not None)
            self.assertTrue("已衰减" in dialog.headroom.text())
            self.assertLess(np.abs(dialog.cache[:, 0]).max(), 1e-5)
            self.assertAlmostEqual(float(dialog.cache[:, 1].max()), 0.98, places=4)
            self.assertIs(dialog.wave.master_audio, dialog.render_mix())
            from vox.studio_session import Session

            np.testing.assert_array_equal(dialog.cache, Session(sources, rate, dialog.state).render())
        finally:
            dialog.reject()
            parent.close()
