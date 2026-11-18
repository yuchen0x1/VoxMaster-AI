"""Produce randomized, level-matched WAV triplets and their separate operator audit."""

from __future__ import annotations
import argparse
import csv
from datetime import datetime
import itertools
import json
from pathlib import Path
import random
import sys
import tempfile
from threading import Event

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.append(str(ROOT / "tests/fixtures"))
from vox.audioio import decode, encode
from vox.service import SR, measure
from audio_acceptance import reference_meter
from render_trials import CATALOG, digest, dump


def calibrated_export(path, audio, gain, target):
    """The absolute BS.1770 gate may change membership when gain changes."""
    with tempfile.TemporaryDirectory(dir=path.parent) as scratch:
        for attempt in range(6):
            temporary = Path(scratch) / (str(attempt) + ".wav")
            encode(temporary, audio * np.float32(10 ** (gain / 20)), SR, bitdepth=24)
            level, peak = reference_meter(temporary)
            if abs(level - target) <= 0.04 and peak <= -1.0:
                if path.exists():
                    raise FileExistsError(path)
                temporary.rename(path)
                return gain, level, peak
            gain += target - level
    raise RuntimeError(
        f"Level calibration failed for {path}: {level:.3f} LUFS, {peak:.3f} dBTP"
    )


def quality(report):
    acoustics = report["acoustics"]
    return dict(
        integrated_lufs=report["lufs"],
        short_term_lufs=report["short_term_lufs"],
        short_term_max_lufs=report["short_term_max_lufs"],
        true_peak_dbtp=report["true_peak_db"],
        rms_dbfs=report["rms_db"],
        crest_factor_db=report["crest_db"],
        dynamic_range_db=report["dynamic_db"],
        centroid_hz=acoustics["centroid_hz"],
        bands_relative_db=report["bands_db"],
        near_full_samples=acoustics["near_full_samples"],
        over_full_samples=acoustics["over_full_samples"],
        rail_plateaus=acoustics["rail_plateau_runs"],
        quiet_frame_p10_dbfs=report["noise_db"],
        correlation=report["stereo_correlation"],
        segments=report["segments"],
        classification=report["classification"],
    )


def generate(root, out):
    engineering = root / "engineering"
    roles = ["original", "0.1.0", "0.1.1"]
    versions = roles[1:]
    # Make the key independent of version/output content. Counterbalance slot order per six trials.
    assignments = list(itertools.permutations(roles))
    rng = random.SystemRandom()
    pool = []
    cases = []
    for item in CATALOG:
        sid = item["id"]
        docs = [
            json.loads(
                (engineering / v / sid / "report.json").read_text(encoding="utf-8")
            )
            for v in versions
        ]
        if (
            docs[0]["clips"] != docs[1]["clips"]
            or docs[0]["source"] != docs[1]["source"]
        ):
            raise ValueError(f"Source or interval mismatch: {sid}")
        for clip in docs[0]["clips"]:
            cases.append((item, clip))
    rng.shuffle(cases)
    out.mkdir(parents=True, exist_ok=False)
    private = out / "engineering"
    listener = out / "listen"
    private.mkdir()
    listener.mkdir()
    device = dict(
        date=datetime.now().astimezone().isoformat(timespec="seconds"),
        render_device="CPU",
        listening_device=None,
        rating_scale="1–5；失真感 1=无明显失真，5=严重。其余维度 5=较好。",
        results="待人工盲听",
    )
    dump(listener / "session.json", device)
    rows = []
    key = {}
    max_spread = 0.0
    max_peak = -1000.0
    for ix, (item, clip) in enumerate(cases, 1):
        if not pool:
            pool = assignments.copy()
            rng.shuffle(pool)
        order = pool.pop()
        code = f"T{ix:02}"
        sid = item["id"]
        token = clip["id"]
        original = engineering / "0.1.0" / sid / (token + "-original.wav")
        files = [original] + [
            engineering / v / sid / (token + "-tuned.wav") for v in versions
        ]
        raw = [decode(f)[0] for f in files]
        if len(set(x.shape for x in raw)) != 1:
            raise RuntimeError(f"Sample alignment mismatch in {token}")
        reports = {role: quality(measure(x, Event())) for role, x in zip(roles, raw)}
        # Use the independently measured levels of each excerpt. A single constant gain preserves dynamics.
        raw_meters = {role: reference_meter(path) for role, path in zip(roles, files)}
        target = min([-23.0] + [lufs + (-1.5 - tp) for lufs, tp in raw_meters.values()])
        if any(v[0] < -65 for v in raw_meters.values()):
            raise ValueError(
                "Insufficient integrated level for a perceptual trial: " + token
            )
        folder = listener / code
        folder.mkdir()
        labels = {}
        for label, role in zip("ABC", order):
            before_lufs = raw_meters[role][0]
            gain = target - before_lufs
            index = roles.index(role)
            target_file = folder / (label + ".wav")
            gain, level, peak = calibrated_export(target_file, raw[index], gain, target)
            labels[label] = dict(
                role=role,
                gain_db=float(gain),
                independent_input_lufs=before_lufs,
                independent_input_dbtp=raw_meters[role][1],
                matched_lufs=level,
                matched_dbtp=peak,
                sha256=digest(target_file),
            )
            rows.append(
                [
                    code,
                    label,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
        levels = [e["matched_lufs"] for e in labels.values()]
        max_spread = max(max_spread, max(levels) - min(levels))
        max_peak = max(max_peak, max(e["matched_dbtp"] for e in labels.values()))
        baseline_wet = raw[1].astype(np.float64)
        delta = raw[2] - baseline_wet
        change_rms = float(np.sqrt(np.mean(delta**2)))
        key[code] = dict(
            source_id=sid,
            source=item,
            clip=clip,
            target_lufs=target,
            quality=reports,
            labels=labels,
            raw_version_delta_rms=change_rms,
            same_samples=np.array_equal(raw[1], raw[2]),
            listening_status="待听审",
        )
        dump(private / (code + ".json"), key[code])
        print(code, token, "spread LU", round(max(levels) - min(levels), 4), flush=True)
    with (listener / "ratings.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "试次",
                "标签",
                "听审人",
                "试听日期",
                "设备/耳机或音箱",
                "监听音量",
                "清晰度",
                "厚度",
                "力量感",
                "自然度",
                "咬字保留",
                "空间感",
                "失真感",
                "偏好(可并列)",
                "问题类型",
                "原片段内秒数",
                "说明",
            ]
        )
        writer.writerows(rows)
    summary = dict(
        trials=len(key),
        wav_count=len(key) * 3,
        peak_dbtp=max_peak,
        max_triplet_loudness_spread_lu=max_spread,
        source_count=len(CATALOG),
        identical_render_pairs=[c for c, v in key.items() if v["same_samples"]],
        date=device["date"],
        listening_status="待人工签字",
    )
    dump(private / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "build/acceptance-011")
    parser.add_argument("--out", type=Path, default=ROOT / "build/acceptance-011/blind")
    args = parser.parse_args()
    generate(args.root, args.out)
