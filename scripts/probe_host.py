"""Independent host, high-DPI, audio-routing and large-file probes on Windows."""

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def dpi():
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from vox.interface import MainWindow
    from vox.visual import STYLES

    app = QApplication([])
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLES)
    display = app.primaryScreen()
    area = display.availableGeometry()
    window = MainWindow()
    window.setAttribute(Qt.WA_DontShowOnScreen)
    window.show()
    app.processEvents()
    views = {}
    for name in ("timeline", "go", "export_btn", "play_btn"):
        widget = getattr(window, name)
        pt = widget.mapTo(window, QPoint(0, 0))
        views[name] = bool(
            widget.isVisible()
            and window.rect().contains(pt)
            and window.rect().contains(pt + QPoint(widget.width() - 1, widget.height() - 1))
        )
    shot = window.grab()
    ready = (
        all(views.values())
        and not shot.isNull()
        and window.width() <= area.width()
        and window.height() <= area.height()
    )
    result = dict(
        status="PASS" if ready else "FAIL",
        platform=app.platformName(),
        dpr=display.devicePixelRatio(),
        displays=len(app.screens()),
        available=[area.width(), area.height()],
        size=[window.width(), window.height()],
        snapshot_pixels=[shot.width(), shot.height()],
        controls=views,
    )
    if getattr(window, "hardware_job", None):
        window.hardware_job.wait(20000)
    window.close()
    app.processEvents()
    return result


def virtual_screens():
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    from vox.interface import MainWindow

    screens = [
        dict(name="A-primary", x=0, width=1920, height=1080, dpr=1),
        dict(name="B-secondary", x=1920, width=2560, height=1600, dpr=1),
    ]
    config = Path(os.environ["VOXMASTER_DATA"]) / "screens.json"
    config.write_text(json.dumps({"screens": screens}), encoding="utf-8")
    os.environ["QT_SCREEN_SCALE_FACTORS"] = "A-primary=1;B-secondary=1.5"
    app = QApplication(["probe", "-platform", f"offscreen:configfile={os.path.relpath(config)}"])
    window = MainWindow()
    window.show()
    app.processEvents()
    results = []
    displays = app.screens()
    for screen in [*displays, displays[0]]:
        window.setScreen(screen)
        window.move(screen.geometry().topLeft() + QPoint(16, 16))
        app.processEvents()
        shot = window.grab()
        results.append(
            dict(
                target=screen.name(),
                actual=window.screen().name(),
                dpr=screen.devicePixelRatio(),
                snapshot_dpr=shot.devicePixelRatio(),
                live=not shot.isNull(),
            )
        )
    passed = len(displays) == 2 and all(
        v["target"] == v["actual"] and v["dpr"] == v["snapshot_dpr"] and v["live"] for v in results
    )
    if getattr(window, "hardware_job", None):
        window.hardware_job.wait(20000)
    window.close()
    app.processEvents()
    return dict(
        status="PASS" if passed else "FAIL", platform=app.platformName(), transitions=results
    )


def route():
    import numpy as np

    from vox import hardware
    from vox.playback import Playback

    endpoints = hardware.devices()
    outputs = [
        e
        for e in endpoints
        if e["outputs"] >= 2
        and "Senary" in e["name"]
        and e["host"] in {"MME", "Windows DirectSound", "Windows WASAPI"}
    ]
    if not outputs:
        outputs = [
            e for e in endpoints if e["outputs"] >= 2 and e["host"] in {"MME", "Windows WASAPI"}
        ]
    if len(outputs) < 2:
        return dict(status="BLOCKED", endpoints=len(outputs))
    player = Playback()
    pcm = np.ones((44100, 2), dtype=np.float32) * 0.002
    player.volume = 0
    player.device = outputs[0]["id"]
    player.play(pcm, 44100, 0.15, 0.85, True)
    events = []
    try:
        for i in range(18):
            endpoint = outputs[(i + 1) % len(outputs)]
            player.device = endpoint["id"]
            time.sleep(0.35)
            events.append(
                dict(
                    id=endpoint["id"],
                    host=endpoint["host"],
                    selected=player.device,
                    playing=player.playing,
                    cursor=round(player.position, 4),
                    underflows=player.underflows,
                    notice=player.device_notice,
                )
            )
        passed = all(
            e["id"] == e["selected"] and e["playing"] and 0.15 <= e["cursor"] < 0.85 for e in events
        )
        return dict(status="PASS" if passed else "FAIL", events=events)
    finally:
        player.stop()


def large():
    import numpy as np

    from vox import audioio

    sr = 44100
    n = sr * 3600
    with tempfile.TemporaryDirectory(prefix="vox-large-") as tmp:
        path = Path(tmp) / "hour.wav"
        original = np.broadcast_to(np.array([0.125, -0.25], "f4"), (n, 2))
        audioio.encode(path, original, sr, 32)
        start = time.perf_counter()
        result, meta = audioio.decode(path)
        secs = time.perf_counter() - start
        valid = (
            isinstance(result, np.memmap)
            and result.shape == original.shape
            and np.array_equal(result[::1021], original[::1021])
        )
        del result
        return dict(
            status="PASS" if valid else "FAIL",
            bytes=path.stat().st_size,
            frames=n,
            duration=meta["duration"],
            decode_seconds=round(secs, 3),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["dpi", "route", "large", "virtual-screens"])
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="vox-host-") as data:
        os.environ["VOXMASTER_DATA"] = data
        result = {"dpi": dpi, "route": route, "large": large, "virtual-screens": virtual_screens}[
            args.kind
        ]()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("x", encoding="utf-8") as f:
        json.dump(
            dict(time=datetime.now().astimezone().isoformat(), kind=args.kind, **result),
            f,
            indent=2,
            ensure_ascii=False,
        )
    if result["status"] != "PASS":
        raise SystemExit(1)
