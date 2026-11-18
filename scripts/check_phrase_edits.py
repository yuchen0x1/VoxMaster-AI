"""Measure regional pitch and tail edits on actual files; export measurements only."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vox import engine
from vox.analysis import pitch_track
from vox.audioio import WORK_RATE as SR
from vox.audioio import decode
from vox.models_runtime import separate


def measure(audio, label):
    report = engine.analyze(audio, SR)
    t, hz, confidence = pitch_track(audio, SR, return_confidence=True)
    voiced = hz > 0
    runs = np.flatnonzero(np.diff(voiced.astype(int), prepend=0, append=0)).reshape(
        -1, 2
    )
    p = engine.recommend(report, "旋律喊麦")
    p["disabled"] = [k for k in engine.STAGES if k != "pitch"]
    auto = engine.process(audio, SR, p)
    result = {
        "material": label,
        "seconds": len(audio) / SR,
        "voiced_frames": int(voiced.sum()),
        "all_frames": len(hz),
        "phrase_candidates": len(report["tail_times"]),
        "voiced_frame_confidence_median": float(np.median(confidence[voiced]))
        if voiced.any()
        else None,
        "auto_changed_peak": float(np.max(np.abs(auto - audio))),
    }
    if len(runs):
        # Prefer a sustained single register for an intentional melodic edit.
        # Keep the unfiltered longest run too, including a guarded zero shift.
        stable = (confidence >= 0.80) & (hz > 0)
        leap = np.abs(12 * np.diff(np.log2(np.maximum(hz, 1)))) > 4.5
        transitional = leap & stable[:-1] & stable[1:]
        stable[1:] &= ~transitional
        stable[:-1] &= ~transitional
        stable_runs = np.flatnonzero(
            np.diff(stable.astype(int), prepend=0, append=0)
        ).reshape(-1, 2)
        probes = {"longest_voiced_run": max(runs, key=lambda r: r[1] - r[0])}
        if len(stable_runs):
            probes["stable_register"] = max(stable_runs, key=lambda r: r[1] - r[0])
        for name, (i, j) in probes.items():
            if j - i < 5:
                continue
            a, b = (
                max(0.0, float(t[i] - 0.009)),
                min(len(audio) / SR, float(t[j - 1] + 0.009)),
            )
            correction = {
                "start": a,
                "end": b,
                "semitones": 2.0,
                "strength": 0.0,
                "speed_ms": 25.0,
            }
            p.update(pitch_regions=[correction], pitch_strength=0.0, semitones=0.0)
            out = engine.process(audio, SR, p)
            _, new_hz = pitch_track(out, SR)
            indices = np.arange(i + 2, j - 1)
            indices = indices[(new_hz[indices] > 0) & (hz[indices] > 0)]
            result.setdefault("manual_pitch", {})[name] = {
                "range_s": [a, b],
                "semitones": 2,
                "common_voiced_frames": len(indices),
                "median_shift_semitones": float(
                    np.median(12 * np.log2(new_hz[indices] / hz[indices]))
                )
                if len(indices)
                else None,
                "outside_selection_max_delta": max(
                    float(
                        np.max(
                            abs(out[: round(a * SR)] - audio[: round(a * SR)]),
                            initial=0,
                        )
                    ),
                    float(
                        np.max(
                            abs(out[round(b * SR) + 1 :] - audio[round(b * SR) + 1 :]),
                            initial=0,
                        )
                    ),
                ),
            }
    candidates = [
        r for r in report["tail_candidates"] if r["candidate"] and r["next_start"]
    ]
    if candidates:
        candidate = max(candidates, key=lambda r: r["gap"])
        a, b = max(candidate["start"], candidate["end"] - 0.24), candidate["end"]
        tail = {
            "start": a,
            "end": b,
            "stretch": 1.5,
            "reverb": 0.2,
            "delay": 0.4,
            "repeats": 4,
            "gain_db": 0.0,
        }
        p = dict(
            engine.PRESETS["经典喊麦"],
            disabled=[k for k in engine.STAGES if k != "space"],
            tail_times=[],
            reverb=0.0,
            delay_ms=160,
            tail_regions=[tail],
        )
        out = engine.process(audio, SR, p)
        k = round(candidate["next_start"] * SR)
        result["manual_tail"] = {
            "range_s": [a, b],
            "next_start": candidate["next_start"],
            "interval_s": candidate["gap"],
            "stretch": 1.5,
            "maximum_change_in_clip": float(np.max(abs(out - audio))),
            "first_150ms_of_next_phrase_max_delta": float(
                np.max(abs(out[k : k + 6615] - audio[k : k + 6615]))
            ),
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mix", type=Path)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dry, _ = decode(ROOT / "tests/fixtures/fleurs-mandarin.wav")
    records = [measure(dry, "FLEURS 真人普通话")]
    if args.mix:
        song, _ = decode(args.mix)
        clip = song[45 * SR : 57 * SR]
        records.append(measure(clip, "本地喊麦成品 45–57 秒"))
        if args.weights:
            vocal, _ = separate(clip, SR, root=args.weights, mode="CPU")
            records.append(measure(vocal, "同一段成品的 Spleeter 估计人声轨"))
    args.output.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
