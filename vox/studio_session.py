"""Sample-accurate non-destructive three-track session. All positions are frame indices."""

from __future__ import annotations

import copy
import math
from pathlib import Path

import numpy as np
from scipy import signal

from .studio_effects import (
    InsertChain,
    VocalKey,
    center_vocal,
    default_rack,
    default_routing,
    validate_options,
)


TRACKS = ("Vocal", "Instrumental", "FX")
BLOCK = 65536


def checked(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("已取消")


def new_clip(source, start, end, at=0):
    return {
        "source": source,
        "start": int(start),
        "end": int(end),
        "at": int(at),
        "env": [],
    }


def duration(clip):
    return clip["end"] - clip["start"]


def envelope(clip, samples):
    points = clip["env"]
    if not points:
        return 1.0
    x, y = zip(*points)
    return np.interp(samples, x, y)


def portion(clip, lo, hi):
    """Take an intersection in timeline coordinates, preserving interpolated automation."""
    a = max(lo, clip["at"]) - clip["at"]
    b = min(hi, clip["at"] + duration(clip)) - clip["at"]
    if a >= b:
        return None
    part = new_clip(clip["source"], clip["start"] + a, clip["start"] + b, clip["at"] + a)
    if clip["env"]:
        nodes = [[0, float(envelope(clip, a))]]
        nodes.extend([x - a, y] for x, y in clip["env"] if a < x < b - 1)
        if b - a > 1:
            nodes.append([b - a - 1, float(envelope(clip, b - 1))])
        part["env"] = nodes
    return part


def load_sources(state, tracks, cancel=None, relink=None):
    """Decode sources referenced by the edit list. Update a relinked path only on success."""
    from .audioio import decode

    result = dict(tracks)
    updated = {}
    for key, name in (state or {}).get("external_sources", {}).items():
        checked(cancel)
        if key in result:
            continue
        path = Path(name)
        if not path.is_file() and relink is not None:
            alternate = relink(str(path))
            if alternate:
                path = Path(alternate)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        result[key], _ = decode(str(path), cancel=cancel)
        updated[key] = str(path.resolve())
    if updated:
        state["external_sources"].update(updated)
    return result


def mixer_strip():
    return dict(gain=0.0, pan=0.0, mute=False, solo=False, highpass=0.0, drive=0.0, clips=[])


def number(value, low, high):
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("工程包含无效的混音参数")
    return value


def sample_index(value, limit):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
        raise ValueError("工程片段位置超出范围")
    return value


class Session:
    def __init__(self, tracks, sr, state=None):
        self.sr = int(sr)
        self.sources = dict(tracks)
        self.source_paths = dict((state or {}).get("external_sources", {}))
        self.undo_stack, self.redo_stack = [], []
        self.clipboard = []
        for array in self.sources.values():
            if array.ndim != 2 or array.shape[1] != 2:
                raise ValueError("多轨素材须为双声道")
        if state:
            self.state = copy.deepcopy(state)
            self.state.setdefault("routing", default_routing())
            self.state.setdefault("racks", {t: default_rack() for t in (*TRACKS, "Master")})
            self.validate()
        else:
            self.state = {
                "schema": 1,
                "rate": self.sr,
                "external_sources": {},
                "tracks": {t: mixer_strip() for t in TRACKS},
                "master_db": 0.0,
                "routing": default_routing(),
                "racks": {t: default_rack() for t in (*TRACKS, "Master")},
            }
            for t in TRACKS:
                if t in tracks and len(tracks[t]):
                    self.strip(t)["clips"].append(new_clip(t, 0, len(tracks[t])))

    def validate(self):
        data = self.state
        if data.get("schema") != 1 or data.get("rate") != self.sr:
            raise ValueError("不兼容的多轨工程版本或采样率")
        number(data["master_db"], -60, 12)
        for name in (*TRACKS, "Master"):
            validate_options(data["racks"][name], data["routing"])
        limit = self.sr * 3600 * 24
        for name in TRACKS:
            row = self.strip(name)
            for key, lo, hi in (
                ("gain", -60, 12),
                ("pan", -1, 1),
                ("highpass", 0, 500),
                ("drive", 0, 4),
            ):
                number(row[key], lo, hi)
            if not isinstance(row["mute"], bool) or not isinstance(row["solo"], bool):
                raise ValueError("无效的轨道开关")
            prev_end = 0
            for clip in row["clips"]:
                key = clip["source"]
                if key not in self.sources:
                    raise ValueError(f"缺少轨道素材 {key}")
                size = len(self.sources[key])
                sample_index(clip["start"], size)
                sample_index(clip["end"], size)
                sample_index(clip["at"], limit)
                n = duration(clip)
                if n <= 0 or clip["at"] < prev_end or clip["at"] + n > limit:
                    raise ValueError("工程片段重叠或长度无效")
                prev_end = clip["at"] + n
                prev = -1
                for x, y in clip["env"]:
                    sample_index(x, n - 1)
                    number(y, 0, 4)
                    if x <= prev:
                        raise ValueError("无效的包络点")
                    prev = x

    def strip(self, track):
        return self.state["tracks"][track]

    @property
    def frames(self):
        return max(
            (c["at"] + duration(c) for t in TRACKS for c in self.strip(t)["clips"]),
            default=0,
        )

    def saved_state(self):
        data = copy.deepcopy(self.state)
        used = {c["source"] for t in TRACKS for c in self.strip(t)["clips"]}
        data["external_sources"] = {
            key: path for key, path in self.source_paths.items() if key in used
        }
        return data

    def checkpoint(self):
        self.undo_stack.append(copy.deepcopy(self.state))
        self.undo_stack = self.undo_stack[-80:]
        self.redo_stack.clear()

    def undo(self, redo=False):
        src, dst = (
            (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        )
        if src:
            dst.append(self.state)
            self.state = src.pop()

    def set_param(self, track, key, value):
        target = self.state if key == "master_db" else self.strip(track)
        if target[key] != value:
            self.checkpoint()
            target[key] = value

    def select(self, track, a, b):
        return [p for c in self.strip(track)["clips"] if (p := portion(c, a, b)) is not None]

    def replace(self, track, a, b, pieces):
        row = self.strip(track)
        old = row["clips"]
        if not 0 <= a <= b <= self.sr * 86400:
            raise ValueError("编辑超出时间轴范围")
        keep = []
        for c in old:
            if c["at"] + duration(c) <= a or c["at"] >= b:
                keep.append(c)
                continue
            for lo, hi in ((0, a), (b, c["at"] + duration(c))):
                section = portion(c, lo, hi)
                if section:
                    keep.append(section)
        changed = sorted(keep + pieces, key=lambda c: c["at"])
        if changed != old:
            self.checkpoint()
            row["clips"] = changed

    def copy_region(self, track, a, b):
        self.clipboard = self.select(track, a, b)
        for c in self.clipboard:
            c["at"] -= a

    def paste(self, track, at):
        if self.clipboard:
            pieces = copy.deepcopy(self.clipboard)
            for c in pieces:
                c["at"] += at
            self.replace(track, at, max(c["at"] + duration(c) for c in pieces), pieces)

    def split(self, track, frame):
        for i, c in enumerate(self.strip(track)["clips"]):
            end = c["at"] + duration(c)
            if c["at"] < frame < end:
                self.checkpoint()
                self.strip(track)["clips"][i : i + 1] = [
                    portion(c, c["at"], frame),
                    portion(c, frame, end),
                ]
                return True
        return False

    def move(self, track, a, b, start):
        """Lift a selection and replace its destination as one undoable edit."""
        pieces = self.select(track, a, b)
        if not pieces or start == a:
            return
        end = start + b - a
        if start < 0 or end > self.sr * 86400:
            raise ValueError("移动位置超出时间轴")
        before = copy.deepcopy(self.state)
        for clip in pieces:
            clip["at"] += start - a
        self.replace(track, a, b, [])
        self.replace(track, start, end, pieces)
        # The two internal replacements form one undo step, even at the history limit.
        self.undo_stack[-2:] = [before]

    def join(self, track, frame):
        clips = self.strip(track)["clips"]
        for i, (a, b) in enumerate(zip(clips, clips[1:])):
            if not a["at"] <= frame <= b["at"] + duration(b):
                continue
            if (
                a["at"] + duration(a) != b["at"]
                or a["source"] != b["source"]
                or a["end"] != b["start"]
            ):
                continue
            merged = new_clip(a["source"], a["start"], b["end"], a["at"])
            if a["env"] or b["env"]:
                nodes = {}
                for clip, off in ((a, 0), (b, duration(a))):
                    nodes[off] = float(envelope(clip, 0))
                    nodes[off + duration(clip) - 1] = float(envelope(clip, duration(clip) - 1))
                    nodes.update({x + off: y for x, y in clip["env"]})
                merged["env"] = [list(p) for p in sorted(nodes.items())]
            self.checkpoint()
            clips[i : i + 2] = [merged]
            return True
        return False

    def fade(self, track, a, b, fade_in):
        pieces = self.select(track, a, b)
        if b - a < 2 or not pieces:
            return
        for c in pieces:
            nodes = {}
            for x in sorted({0, duration(c) - 1, *(p[0] for p in c["env"])}):
                f = (c["at"] + x - a) / (b - a - 1)
                nodes[x] = float(envelope(c, x) * (f if fade_in else 1 - f))
            c["env"] = [list(p) for p in nodes.items()]
        self.replace(track, a, b, pieces)

    def point(self, track, frame, gain):
        for c in self.strip(track)["clips"]:
            loc = frame - c["at"]
            if 0 <= loc < duration(c):
                self.checkpoint()
                nodes = {0: 1.0, duration(c) - 1: 1.0}
                nodes.update(dict(c["env"]))
                nodes[loc] = float(number(gain, 0, 4))
                c["env"] = [list(p) for p in sorted(nodes.items())]
                return True
        return False

    def import_clip(self, track, key, path, audio, at):
        if not len(audio):
            raise ValueError("音轨没有有效采样")
        clip = new_clip(key, 0, len(audio), at)
        self.replace(track, at, at + len(audio), [clip])
        self.sources[key] = audio
        self.source_paths[key] = str(Path(path).resolve())
        self.state["external_sources"][key] = self.source_paths[key]

    def set_rack(self, name, rack):
        validate_options(rack)
        if rack != self.state["racks"][name]:
            self.checkpoint()
            self.state["racks"][name] = copy.deepcopy(rack)

    def configure_balance(self, routing, music_gain, vocal_pan=None):
        validate_options(default_rack(), routing)
        number(music_gain, -60, 12)
        if vocal_pan is not None:
            number(vocal_pan, -1, 1)
        self.checkpoint()
        self.state["routing"] = copy.deepcopy(routing)
        self.strip("Instrumental")["gain"] = music_gain
        if vocal_pan is not None:
            self.strip("Vocal")["pan"] = vocal_pan

    def _strip_blocks(self, name, size, cancel):
        row = self.strip(name)
        pan = row["pan"]
        gain = 10 ** (row["gain"] / 20.0)
        angle = (pan + 1) * math.pi / 4
        left_gain = math.sqrt(2) * math.cos(angle)
        right_gain = math.sqrt(2) * math.sin(angle)
        sos = (
            signal.butter(2, row["highpass"], fs=self.sr, btype="highpass", output="sos")
            if row["highpass"]
            else None
        )
        clips = row["clips"]
        if not clips:
            return
        chain = InsertChain(self.state["racks"][name], self.sr)
        index = 0
        state = np.zeros((len(sos), 2, 2)) if sos is not None else None
        for start in range(0, size, BLOCK):
            checked(cancel)
            end = min(start + BLOCK, size)
            chunk = np.zeros((end - start, 2), np.float32)
            while index < len(clips):
                c = clips[index]
                stop = c["at"] + duration(c)
                if c["at"] >= end:
                    break
                left, right = max(start, c["at"]), min(end, stop)
                offset = left - c["at"]
                if right > left:
                    sample = c["start"] + offset
                    dest = chunk[left - start : right - start]
                    np.copyto(dest, self.sources[c["source"]][sample : sample + right - left])
                    if c["env"]:
                        dest *= envelope(c, np.arange(offset, offset + len(dest)))[:, None]
                if stop > end:
                    break
                index += 1
            if sos is not None:
                chunk, state = signal.sosfilt(sos, chunk, axis=0, zi=state)
            drive = row["drive"]
            if drive:
                chunk = np.tanh(chunk * (1 + drive)) / np.tanh(1 + drive)
            if name == "Vocal" and self.state["routing"]["enabled"]:
                chunk = center_vocal(chunk, self.state["routing"]["center"])
            if pan:
                # Equal-power pan of the mid signal. Narrow the side component
                # toward the extremes so either input channel can cross center.
                mid = (chunk[:, 0] + chunk[:, 1]) * 0.5
                side = (chunk[:, 0] - chunk[:, 1]) * (0.5 * (1 - abs(pan)))
                chunk[:, 0] = mid * left_gain + side
                chunk[:, 1] = mid * right_gain - side
            yield chain.apply(chunk * gain)

    def render(self, cancel=None, track=None, *, metrics=None):
        """Mix frame-aligned blocks; derive the sidechain from edited, post-fader vocal."""
        checked(cancel)
        size = self.frames
        if size * 8 > _available_bytes() * 0.65:
            raise MemoryError("混音缓冲区超出可用内存，请缩短工程或释放内存")
        output = np.zeros((size, 2), dtype=np.float32)
        soloed = any(self.strip(t)["solo"] for t in TRACKS)
        audible = {
            name
            for name in TRACKS
            if (
                (name == track)
                if track
                else (not self.strip(name)["mute"] and (not soloed or self.strip(name)["solo"]))
            )
        }
        routing = self.state["routing"]
        use_key = (
            routing["enabled"]
            and "Instrumental" in audible
            and bool(self.strip("Instrumental")["clips"])
            and (routing["duck_db"] or routing["mask_db"])
        )
        streams = {
            name: self._strip_blocks(name, size, cancel)
            for name in TRACKS
            if self.strip(name)["clips"]
            and (name in audible or (use_key and name == "Vocal" and not self.strip(name)["mute"]))
        }
        key = VocalKey(routing, self.sr) if use_key else None
        bus = InsertChain(self.state["racks"]["Master"], self.sr) if track is None else None
        for start in range(0, size, BLOCK):
            checked(cancel)
            blocks = {name: next(stream) for name, stream in streams.items()}
            if key:
                blocks["Instrumental"] = key.process(blocks["Instrumental"], blocks.get("Vocal"))
            combined = output[start : start + BLOCK]
            for name, chunk in blocks.items():
                if name in audible:
                    combined += chunk
            if bus:
                combined[:] = bus.apply(combined)
        gain = 10 ** ((self.state["master_db"] if track is None else 0.0) / 20)
        peak = 0.0
        for start in range(0, size, BLOCK):
            checked(cancel)
            peak = max(peak, float(np.abs(output[start : start + BLOCK]).max()))
        peak_requested = peak * gain
        protection = min(1.0, 0.98 / max(peak_requested, 1e-20))
        gain *= protection
        if metrics is not None:
            metrics.update(
                pre_peak_db=20 * math.log10(max(peak_requested, 1e-6)),
                peak_db=20 * math.log10(max(peak * gain, 1e-6)),
                reduction_db=-20 * math.log10(protection),
            )
        for start in range(0, size, BLOCK):
            checked(cancel)
            output[start : start + BLOCK] *= gain
        return output


def _available_bytes():
    import os

    if os.name == "nt":
        import ctypes

        class Memory(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                ("total", ctypes.c_ulonglong),
                ("available", ctypes.c_ulonglong),
                ("rest", ctypes.c_ulonglong * 5),
            ]

        status = Memory()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.available
    return 2**33
