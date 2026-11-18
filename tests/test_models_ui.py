"""Model center controls with deterministic resumable HTTP transfers."""

import hashlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from vox.models import ModelDialog
from vox import models_store as store


class ModelControlsTest(unittest.TestCase):
    def test_download_pause_continue_verify_reinstall_cancel_migrate_delete(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        body = bytes(range(256)) * 8192
        size = len(body)
        sha = hashlib.sha256(body).hexdigest()
        ranges = []

        class Origin(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                header = self.headers.get("Range")
                offset = int(header[6:-1]) if header else 0
                ranges.append(offset)
                self.send_response(206 if offset else 200)
                if offset:
                    self.send_header("Content-Range", f"bytes {offset}-{size - 1}/{size}")
                self.send_header("Content-Length", str(size - offset))
                self.end_headers()
                try:
                    for pos in range(offset, size, 65536):
                        self.wfile.write(body[pos : pos + 65536])
                        self.wfile.flush()
                        time.sleep(0.004)
                except (ConnectionError, OSError):
                    pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def wait(check):
            limit = time.monotonic() + 15
            while not check() and time.monotonic() < limit:
                app.processEvents()
                time.sleep(0.005)
            self.assertTrue(check(), "模型中心事件超时")

        def click(button):
            self.assertTrue(button.isEnabled(), button.text())
            QTest.mouseClick(button, Qt.LeftButton)

        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, VOXMASTER_DATA=temp),
            patch.object(store, "SIZE", size * 2),
            patch.object(store, "BASE", f"http://127.0.0.1:{server.server_port}"),
            patch.dict(store.FILES, {n: (size, sha) for n in store.FILES}),
        ):
            dlg = ModelDialog()
            dlg.show()
            app.processEvents()
            try:
                with patch("vox.models.QMessageBox.information") as info:
                    click(dlg.details)
                    self.assertIn(store.REVISION, info.call_args.args[-1])
                with patch(
                    "urllib.request.urlopen",
                    return_value=io.BytesIO(json.dumps({"sha": store.REVISION}).encode()),
                ):
                    click(dlg.update)
                    wait(lambda: dlg.task is None)
                    self.assertEqual(dlg.message.text(), "当前已是上游版本")
                click(dlg.start)
                wait(lambda: 510 <= dlg.progress.value() < 990)
                click(dlg.pause)
                wait(lambda: dlg.task is None)
                self.assertEqual(dlg.start.text(), "继续下载")
                self.assertFalse((store.directory() / "vocals.onnx").exists())
                click(dlg.start)
                wait(lambda: dlg.task is None)
                self.assertTrue(any(offset > 0 for offset in ranges))
                self.assertEqual(dlg.start.text(), "重新下载")
                click(dlg.check)
                wait(lambda: dlg.task is None)
                self.assertIn("SHA-256", dlg.message.text())
                click(dlg.start)
                wait(lambda: 10 <= dlg.progress.value() < 990)
                click(dlg.cancel)
                wait(lambda: dlg.task is None)
                store.verify()
                self.assertFalse(any(store.directory().glob("*.part")))
                new_dir = str(Path(temp) / "new-location")
                with patch("vox.models.QFileDialog.getExistingDirectory", return_value=new_dir):
                    click(dlg.migrate)
                    wait(lambda: dlg.task is None)
                # Runners may hand out 8.3 short temp paths; migrate records the long form.
                self.assertEqual(store.directory().parent, Path(new_dir).resolve())
                store.verify()
                dlg.mode.setCurrentIndex(dlg.mode.findData("CPU"))
                dlg.close()
                dlg = ModelDialog()
                dlg.show()
                app.processEvents()
                self.assertEqual(dlg.mode.currentData(), "CPU")
                self.assertIn("已安装", dlg.state.text())
                with patch("vox.models.QMessageBox.question", return_value=QMessageBox.Yes):
                    click(dlg.delete)
                    wait(lambda: dlg.task is None)
                self.assertIn("尚未下载", dlg.state.text())
                click(dlg.start)
                wait(lambda: 510 <= dlg.progress.value() < 990)
                click(dlg.cancel)
                wait(lambda: dlg.task is None)
                self.assertEqual(dlg.start.text(), "下载模型")
                self.assertFalse(any(store.directory().glob("*.onnx*")))
            finally:
                if dlg.task:
                    dlg.task.stop.set()
                    dlg.task.wait(16000)
                    app.processEvents()
                dlg.close()
