"""Prepare a two-version blind pilot for a live listener. Keep the answer key outside listen/."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import secrets
import numpy as np
from blind_trials import ROOT, SR, decode, encode, reference_meter, dump


def create(out, case_id, base):
    versions = ["0.1.0", "0.1.1"]
    reports = {}
    for version in versions:
        folder = base / "engineering" / version / case_id
        report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
        clip = report["clips"][0]
        reports[version] = (clip, folder / (clip["id"] + "-tuned.wav"), report)
    times = [value[0] for value in reports.values()]
    if times[0] != times[1]:
        raise ValueError("Different source intervals")
    levels = {v: reference_meter(reports[v][1]) for v in versions}
    target = min([-23.0] + [lufs - 1.5 - tp for lufs, tp in levels.values()])
    # Equal probability of each assignment; do not print the key in a live trial.
    secrets.SystemRandom().shuffle(versions)
    out.mkdir(parents=True, exist_ok=False)
    public = out / "listen"
    public.mkdir()
    key = {}
    for label, version in zip("AB", versions):
        audio = decode(reports[version][1])[0]
        gain = target - levels[version][0]
        file = public / (label + ".wav")
        encode(file, audio * np.float32(10 ** (gain / 20)), SR, bitdepth=24)
        actual, tp = reference_meter(file)
        if abs(actual - target) > 0.1 or tp > -1.0:
            raise ValueError("Level calibration failed")
        key[label] = dict(
            version=version,
            lufs=actual,
            true_peak=tp,
            gain_db=gain,
            implementation=reports[version][2]["implementation"],
        )
    dump(out / "operator-key.json", key)
    info = dict(
        date=datetime.now().astimezone().isoformat(timespec="seconds"),
        case=case_id,
        start_s=times[0]["start_frame"] / SR,
        end_s=times[0]["end_frame"] / SR,
        matched_lufs=target,
        difference_lu=abs(key["A"]["lufs"] - key["B"]["lufs"]),
        human_response=None,
    )
    dump(public / "trial.json", info)
    print(info)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "build/acceptance-011")
    parser.add_argument("--case", default="MC01")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    create(args.out, args.case, args.root)
