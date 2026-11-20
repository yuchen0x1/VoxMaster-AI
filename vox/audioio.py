"""Local file codecs. The workstation bus is 44.1 kHz dual-channel float PCM."""

from __future__ import annotations

import math
import os
import re
import shutil
import tempfile
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

WORK_RATE = 44100
OUTPUT_RATES = (44100, 48000, 88200, 96000)
IMPORT_EXTENSIONS = (".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".aiff", ".aif")
_DEMUXERS = "wav,mp3,flac,mov,aac,ogg,aiff"
_SPOOL_BYTES = 64 * 1024**2
_cache_directory = None


def cache_directory():
    """Return the active spool directory, including a startup fallback to default."""
    return _cache_directory


def set_cache_directory(path):
    """Applies to subsequently opened audio files; live mappings remain valid."""
    global _cache_directory
    if not path:
        _cache_directory = None
        return
    directory = Path(path).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=directory):
        pass
    _cache_directory = directory


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("操作已取消")


def _bit_depth(codec):
    match = re.fullmatch(r"pcm_[suf](\d+)(be|le)?", codec.name)
    if match:
        return int(match.group(1))
    if codec.name == "flac" and codec.extradata and len(codec.extradata) == 34:
        # STREAMINFO packs rate, channel count and bit depth into adjacent fields.
        return ((int.from_bytes(codec.extradata[12:14], "big") >> 4) & 31) + 1
    return None


def decode(path, cancel=None):
    """Return contiguous stereo PCM and the *source* metadata. Never modify input."""
    path = Path(path)
    if path.suffix.lower() not in IMPORT_EXTENSIONS or not path.is_file():
        raise ValueError("请选择现有的 WAV、MP3、FLAC、M4A、AAC、OGG 或 AIFF 文件")
    _check_cancel(cancel)
    # Large files spill to a temporary mapping. The mapping remains alive for
    # precisely as long as its numpy views, including after this handle closes.
    with (
        tempfile.SpooledTemporaryFile(max_size=_SPOOL_BYTES, dir=_cache_directory) as spool,
        path.open("rb") as source,
    ):
        with av.open(
            source, options={"format_whitelist": _DEMUXERS, "protocol_whitelist": "file"}
        ) as container:
            if not container.streams.audio:
                raise ValueError("文件中没有音轨")
            stream = container.streams.audio[0]
            codec = stream.codec_context
            mono = codec.channels == 1
            resampler = av.AudioResampler(
                format="flt", layout="mono" if mono else "stereo", rate=WORK_RATE
            )
            meta = dict(
                sample_rate=codec.sample_rate,
                channels=codec.channels,
                bit_depth=_bit_depth(codec),
                codec=codec.name,
                format=container.format.name,
                path=str(path.resolve()),
            )

            def write_frames(frame):
                for block in resampler.resample(frame):
                    pcm = block.to_ndarray().reshape(-1, 1 if mono else 2)
                    if not np.isfinite(pcm).all():
                        raise ValueError("音频包含无效浮点采样")
                    if mono:
                        pcm = np.repeat(pcm, 2, axis=1)
                    spool.write(memoryview(np.ascontiguousarray(pcm)).cast("B"))

            for frame in container.decode(stream):
                _check_cancel(cancel)
                write_frames(frame)
            write_frames(None)
            # MOV edit lists carry the valid AAC duration. The final AAC frame
            # can otherwise add up to 1023 silent samples on every round trip.
            if codec.name == "aac" and "mov" in container.format.name and stream.duration:
                valid = round(stream.duration * stream.time_base * WORK_RATE)
                if valid > 0 and valid * 8 < spool.tell():
                    spool.truncate(valid * 8)
                    spool.seek(0, os.SEEK_END)
        _check_cancel(cancel)
        size = spool.tell()
        if not size:
            raise ValueError("音轨中没有可解码的采样")
        spool.seek(0)
        if size > _SPOOL_BYTES:
            pcm = np.memmap(spool, mode="c", dtype=np.float32, shape=(size // 8, 2))
        else:
            pcm = np.empty((size // 8, 2), dtype=np.float32)
            spool.readinto(memoryview(pcm).cast("B"))
    meta["duration"] = len(pcm) / WORK_RATE
    return pcm, meta


def estimate_size(seconds, format, rate=WORK_RATE, bitdepth=24, channels=2):
    kind = str(format).lower().lstrip(".")
    if kind in {"mp3", "aac", "m4a"}:
        return math.ceil(seconds * _bitrate(kind, channels) / 8) + 4096
    raw = seconds * rate * channels * bitdepth / 8
    return math.ceil(raw * (0.65 if kind == "flac" else 1)) + 128


def _bitrate(kind, channels):
    return channels * (160000 if kind == "mp3" else 128000)


def encode(path, audio, sr, bitdepth=24, cancel=None, *, output_rate=None, channels=2):
    """Encode to a sibling temporary file and publish only if destination is new."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"文件已存在，请选择新文件名：{path.name}")
    _check_cancel(cancel)
    audio = np.asarray(audio)
    if audio.ndim == 1:
        audio = audio[:, None]
    if not len(audio) or audio.ndim != 2 or audio.shape[1] not in (1, 2):
        raise ValueError("需要非空的单声道或立体声音轨")
    rate = int(output_rate or sr)
    if sr <= 0 or channels not in (1, 2) or rate not in OUTPUT_RATES:
        raise ValueError("导出支持单声道、立体声和 44.1、48、88.2、96 kHz")
    kind = path.suffix.lower().lstrip(".")
    if kind not in {"wav", "flac", "mp3", "aac", "m4a"}:
        raise ValueError("可导出 WAV、FLAC、MP3 或 AAC")
    if kind == "mp3" and rate > 48000:
        raise ValueError("MP3 编码支持 44.1 或 48 kHz")
    if kind == "wav" and bitdepth not in (16, 24, 32):
        raise ValueError("WAV 位深支持 16、24 或 32 位浮点")
    if kind == "flac" and bitdepth not in (16, 24):
        raise ValueError("FLAC 位深支持 16 或 24 位")
    if kind == "wav":
        pcm_bytes = math.ceil(len(audio) * rate / sr) * channels * (bitdepth // 8)
        if shutil.disk_usage(path.parent).free < pcm_bytes + 128:
            raise OSError("目标磁盘空间不足，请选择其他导出目录。")
    codec = {"mp3": "libmp3lame", "aac": "aac", "m4a": "aac", "flac": "flac"}.get(kind)
    codec = codec or {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_f32le"}[bitdepth]
    muxer = {"m4a": "ipod", "aac": "adts"}.get(kind, kind)
    layout = "stereo" if channels == 2 else "mono"
    fd, name = tempfile.mkstemp(prefix=".vox-", suffix=".part", dir=path.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        options = {"rf64": "auto"} if kind == "wav" else {}
        with av.open(str(temporary), "w", format=muxer, options=options) as container:
            stream = container.add_stream(codec, rate=rate)
            stream.layout = layout
            if kind == "flac":
                stream.format = "s32" if bitdepth == 24 else "s16"
            if kind in ("mp3", "aac", "m4a"):
                stream.bit_rate = _bitrate(kind, channels)
            for start in range(0, len(audio), 16384):
                _check_cancel(cancel)
                samples = np.asarray(audio[start : start + 16384], dtype=np.float32)
                if not np.isfinite(samples).all():
                    raise ValueError("导出音频包含无效浮点采样")
                if samples.shape[1] != channels:
                    samples = (
                        samples.mean(axis=1, keepdims=True)
                        if channels == 1
                        else np.repeat(samples, 2, axis=1)
                    )
                packed = np.ascontiguousarray(samples).reshape(1, -1)
                frame = av.AudioFrame.from_ndarray(packed, format="flt", layout=layout)
                frame.sample_rate = int(sr)
                frame.time_base = Fraction(1, int(sr))
                frame.pts = start
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        _check_cancel(cancel)
        if os.name == "nt":
            # On Windows os.rename is a no-replace move, including on FAT/exFAT.
            os.rename(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
