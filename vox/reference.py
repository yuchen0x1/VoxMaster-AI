"""Compare like sections across recordings with different arrangements."""

from bisect import bisect_right
import numpy as np
from .acoustics import space_evidence

ROLES = ("开头", "普通发声", "高能量", "拖腔", "尾音", "结束")
BANDS = {"body": "低频厚度", "mud": "低中频", "presence": "咬字清晰度", "air": "高频空气感"}


def role_for(part):
    if part.get("tail") or part["label"] == "尾音":
        return "尾音"
    if part.get("sustained") or part["label"] in ("拖腔", "旋律段"):
        return "拖腔"
    if part.get("high_energy") or part["label"] in ("强爆发音", "高能量段"):
        return "高能量"
    return "普通发声"


def role_groups(report):
    result = {key: [] for key in ROLES}
    duration = report["duration"]
    edge = min(8.0, duration * 0.15)
    for segment in report.get("segments", []):
        if segment["label"] == "静音" or segment["level_db"] <= -65:
            continue
        role = role_for(segment)
        if role != "普通发声" or segment["label"] in ("普通语音", "快速咬字"):
            result[role].append(segment)
        if segment["start"] < edge:
            result["开头"].append(segment)
        if segment["end"] > duration - edge:
            result["结束"].append(segment)
    return result


def measure_role_space(audio, sr, report, cancel=None):
    result = {}
    for role, parts in role_groups(report).items():
        if not parts:
            continue
        # Keep the context contiguous: joining unrelated excerpts could invent echoes.
        part = max(parts, key=lambda p: p["end"] - p["start"])
        a = max(0, part["start"] - 0.5)
        b = min(report["duration"], part["end"] + 0.55, a + 8.0)
        tails = [t - a for t in report["tail_times"] if a <= t <= b]
        local = audio[round(a * sr) : round(b * sr)]
        if len(local) < sr * 0.12:
            continue
        result[role] = dict(start=a, end=b, **space_evidence(local, sr, tails, cancel))
    return result


def summarize(parts):
    weights = np.array([max(0.001, s["end"] - s["start"]) for s in parts])

    def median(values):
        order = np.argsort(values)
        pos = np.searchsorted(np.cumsum(weights[order]), weights.sum() / 2)
        return float(np.array(values)[order[pos]])

    result = {k: median([p["bands_db"][k] for p in parts]) for k in BANDS}
    for k in ("dynamic_db", "side_fraction", "k_level"):
        result[k] = median([p[k] for p in parts])
    return result


def comparison(report, reference):
    source, ref = role_groups(report), role_groups(reference)
    result = []
    for role in ROLES:
        current, other = source[role], ref[role]
        row = {"role": role, "source_count": len(current), "reference_count": len(other)}
        if current and other:
            a, b = summarize(current), summarize(other)
            row["diff"] = {k: b[k] - a[k] for k in a}
            representative = report.get("role_space", {}).get(role) or max(
                current, key=lambda p: p["end"] - p["start"]
            )
            row["interval"] = (representative["start"], representative["end"])
            row["relative_level"] = row["diff"]["k_level"] - (
                reference.get("lufs", 0) - report.get("lufs", 0)
            )
            row["space"] = space_notes(
                {"acoustics": report.get("role_space", {}).get(role, {})},
                {"acoustics": reference.get("role_space", {}).get(role, {})},
            )
        result.append(row)
    return result


def match_segments(params, report, reference):
    """Adjust existing automation in place; independent of reference duration."""
    rows = comparison(report, reference)
    diffs = {r["role"]: r["diff"] for r in rows if "diff" in r}
    segments = report.get("segments", [])
    if not segments:
        return params
    starts = [p["start"] for p in segments]
    duration = report["duration"]
    for control in params.get("automation", []):
        mid = (control["start"] + control["end"]) * 0.5
        part = segments[max(0, bisect_right(starts, mid) - 1)]
        if part["label"] == "静音":
            continue
        role = role_for(part)
        edge = min(8.0, duration * 0.15)
        edge_role = "开头" if mid < edge else "结束" if mid > duration - edge else None
        differences = [diffs[key] for key in (role, edge_role) if key in diffs]
        if not differences:
            continue
        strength = 0.15 + 0.2 * float(np.clip(part["confidence"], 0.0, 1.0))
        for band in BANDS:
            key = band + "_delta_db"
            movement = np.mean([d[band] for d in differences]) * strength
            control[key] = float(np.clip(control.get(key, 0) + np.clip(movement, -1.5, 1.5), -3, 3))
        dynamic = np.mean([d["dynamic_db"] for d in differences])
        control["ratio_scale"] = float(
            np.clip(control.get("ratio_scale", 1) - dynamic * 0.025, 0.7, 1.45)
        )
        relative_level = np.mean([d["k_level"] for d in differences]) - (
            reference.get("lufs", 0) - report.get("lufs", 0)
        )
        offset = np.clip(relative_level * 0.2, -1.5, 1.5)
        control["threshold_delta_db"] = float(
            np.clip(control.get("threshold_delta_db", 0) + offset, -8, 8)
        )
    # Echo can arise from repeating accompaniment. Limit recommendations to an
    # audible nudge to an already enabled delay of the same timing family.
    a = report.get("acoustics", {}).get("repeat_delay_ms")
    b = reference.get("acoustics", {}).get("repeat_delay_ms")
    if a and b and params["delay"] and params["delay_type"] != "Tempo":
        params["delay_ms"] = float(
            np.clip(params["delay_ms"] + np.clip((b - a) * 0.2, -35, 35), 40, 1200)
        )
    return params


def describe_match(row):
    if "diff" not in row:
        return "至少一条录音缺少对应发声段，保留原有处理。"
    delta = row["diff"]
    lines = [
        f"参与比较的段落    当前 {row['source_count']} 段    参考 {row['reference_count']} 段",
        f"参考减当前的 K 加权段电平差 {delta['k_level']:+.1f} LU，活动动态差 {delta['dynamic_db']:+.1f} dB。",
    ]
    for band, name in BANDS.items():
        change = float(np.clip(0.25 * delta[band], -1.5, 1.5))
        lines.append(
            f"{name}差 {delta[band]:+.1f} dB。均衡器建议 {min(0, change):+.1f} 至 {max(0, change):+.1f} dB，试听该频区的音色变化。"
        )
    ratio = float(np.clip(1 - 0.025 * delta["dynamic_db"], 0.7, 1.45))
    lines.append(f"段落压缩比建议乘 {min(1, ratio):.2f}–{max(1, ratio):.2f}，比较爆发音与后续咬字。")
    threshold = float(np.clip(row["relative_level"] * 0.2, -1.5, 1.5))
    lines.append(
        f"扣除全曲响度差后，段落电平差 {row['relative_level']:+.1f} LU。压缩阈值建议偏移 {min(0, threshold):+.1f} 至 {max(0, threshold):+.1f} dB，比较该段与相邻段的强弱。"
    )
    width = float(np.clip(delta["side_fraction"], -0.2, 0.2))
    lines.append(
        f"侧声道能量占比差 {100 * delta['side_fraction']:+.1f} 个百分点；宽度参数建议微调 {min(0, width):+.2f} 至 {max(0, width):+.2f}，复听单声道。"
    )
    return "\n".join(lines + row.get("space", []))


def space_notes(report, reference):
    current = report.get("acoustics", {})
    ref = reference.get("acoustics", {})
    notes = []
    for key, label, unit, scale, bound, control in (
        ("decay20_s", "尾部衰减时间", "秒", 0.25, 0.18, "混响 Decay"),
        ("repeat_delay_ms", "重复纹理间隔", "ms", 0.2, 35, "延迟时间"),
    ):
        a, b = current.get(key), ref.get(key)
        if a is None or b is None:
            notes.append(f"{label}缺少两侧共同证据，保留当前时间参数。")
        else:
            change = float(np.clip((b - a) * scale, -bound, bound))
            notes.append(
                f"{label}差 {b - a:+.2f} {unit}；{control} 建议微调 {min(0, change):+.2f} 至 {max(0, change):+.2f} {unit}，检查是否遮挡下一句。"
            )
    return notes
