"""Playback of already-rendered PCM through PortAudio. Times are in seconds."""

import math
import time
from weakref import WeakSet

import numpy as np
import sounddevice as sd

from .hardware import device_lock

_transports = WeakSet()


def refresh_endpoints():
    """PortAudio v19 snapshots Windows endpoints at initialization. Refresh only at rest."""
    with device_lock:
        if any(p._stream is not None for p in _transports):
            return False
        # The pinned sounddevice build exposes paired PortAudio lifetime hooks.
        # Its own interpreter-exit refcount stays balanced after each refresh.
        if sd._initialized > 0:
            sd._terminate()
        sd._initialize()
        return True


class Playback:
    def __init__(self):
        self._stream = None
        self._cursor = 0
        self._sr = 44100
        self._playing = False
        self._volume = 0.8
        self._device = None
        self._source = None
        self._input = None
        self._input_shape = None
        self._region = None
        self._last_callback = None
        self._reached_end = False
        self._recovered_at = None
        self.device_notice = ""
        self.underflows = 0
        _transports.add(self)

    @property
    def playing(self):
        return self._playing

    @property
    def position(self):
        return self._cursor / self._sr

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value):
        v = float(value)
        if not math.isfinite(v):
            raise ValueError("音量无效")
        self._volume = min(1.0, max(0.0, v))

    @property
    def device(self):
        return self._device

    @device.setter
    def device(self, value):
        if self._device != value:
            resume = self._resume_state()
            self._device = value
            if resume:
                self._open(*resume)

    def play(self, audio, sr, start=0, end=None, loop=False):
        self.device_notice = ""
        self._recovered_at = None
        self._open(audio, sr, start, end, loop, start)

    def _resume_state(self):
        if (
            self._last_callback is None
            or self._source is None
            or self._region is None
            or self._reached_end
        ):
            return None
        first, last, loop = self._region
        return self._input, self._sr, first, last, loop, self.position

    def poll_device(self):
        """Called by the GUI timer. Recover stopped or unresponsive device streams once."""
        if self._last_callback is None or self._reached_end:
            return ""
        if self._playing and time.monotonic() - self._last_callback < 3:
            return ""
        resume = self._resume_state()
        if not resume:
            return ""
        if self._recovered_at is not None and self._last_callback - self._recovered_at < 3:
            self.pause()
            self.device_notice = "默认输出没有持续返回音频数据，请连接设备后重新播放。"
            return self.device_notice
        self._device = None
        try:
            self._recovered_at = time.monotonic()
            self.pause()
            refresh_endpoints()
            self._open(*resume)
            self.device_notice = "输出设备断开，已尝试恢复 Windows 默认设备。"
        except (sd.PortAudioError, ValueError, OSError) as exc:
            self.pause()
            self.device_notice = f"音频设备已断开，请连接设备后重新播放。{exc}"
        return self.device_notice

    def _open(self, audio, sr, start, end, loop, resume_at):
        with device_lock:
            try:
                self._open_device(audio, sr, start, end, loop, resume_at)
            except (sd.PortAudioError, OSError):
                self.pause()
                selected = self._device
                self._device = None
                if not refresh_endpoints() and selected is None:
                    raise
                self._open_device(audio, sr, start, end, loop, resume_at)
                self.device_notice = "所选设备不可用，已切换到 Windows 默认输出。"

    def _open_device(self, audio, sr, start, end, loop, resume_at):
        self.pause()
        samples = np.asarray(audio, dtype=np.float32)
        if samples.ndim == 1:
            samples = samples[:, None]
        if samples.ndim != 2 or samples.shape[1] not in (1, 2) or sr <= 0:
            raise ValueError("试听需要单声道或立体声 PCM")
        first = min(len(samples), max(0, round(start * sr)))
        last = len(samples) if end is None else min(len(samples), round(end * sr))
        self._cursor, self._sr = min(last, max(first, round(resume_at * sr))), sr
        if last <= first:
            return
        if self._cursor >= last:
            self._cursor = first
        info = sd.query_devices(self._device, "output")
        channels = min(2, info["max_output_channels"], samples.shape[1])
        if not channels:
            raise ValueError("音频设备没有输出声道")
        self._input_shape = samples.shape
        self._input = samples
        if channels < samples.shape[1]:
            samples = samples.mean(axis=1, keepdims=True)
        self._source = samples
        self._region = (first / sr, last / sr, loop)
        self._reached_end = False
        fade_count = min(max(1, round(sr * 0.003)), (last - first) // 2)
        fade = np.linspace(0.0, 1.0, fade_count, dtype=np.float32)[:, None]
        previous = None
        blend_at = 0
        active = samples
        scratch = np.empty((fade_count, channels), dtype=np.float32)
        self.underflows = 0

        def fill(outdata, frames, time_info, status):
            nonlocal active, previous, blend_at
            self._last_callback = time.monotonic()
            if status.output_underflow:
                self.underflows += 1
            next_source = self._source
            if next_source is not None and next_source is not active:
                previous, active, blend_at = active, next_source, 0
            used = 0
            while used < frames:
                cursor = self._cursor
                count = min(frames - used, last - cursor)
                segment = outdata[used : used + count]
                np.copyto(segment, active[cursor : cursor + count])
                if previous is not None:
                    blend = min(fade_count - blend_at, count)
                    if blend:
                        segment[:blend] *= fade[blend_at : blend_at + blend]
                        np.multiply(
                            previous[cursor : cursor + blend],
                            fade[::-1][blend_at : blend_at + blend],
                            out=scratch[:blend],
                        )
                        segment[:blend] += scratch[:blend]
                        blend_at += blend
                    if blend_at == fade_count:
                        previous = None
                segment *= self._volume
                # Taper the transport boundaries without changing the render.
                attack = min(count, first + fade_count - cursor)
                if attack > 0:
                    segment[:attack] *= fade[cursor - first : cursor - first + attack]
                release = min(count, cursor + count - (last - fade_count))
                if release > 0:
                    idx = last - (cursor + count)
                    segment[-release:] *= fade[idx : idx + release][::-1]
                used += count
                self._cursor += count
                if self._cursor == last:
                    if loop:
                        self._cursor = first
                    else:
                        outdata[used:].fill(0)
                        self._reached_end = True
                        raise sd.CallbackStop

        def finished():
            self._playing = False

        wasapi = (
            "hostapi" in info and sd.query_hostapis(info["hostapi"])["name"] == "Windows WASAPI"
        )
        stream = sd.OutputStream(
            samplerate=sr,
            channels=channels,
            dtype="float32",
            device=self._device,
            extra_settings=sd.WasapiSettings(auto_convert=True) if wasapi else None,
            callback=fill,
            finished_callback=finished,
        )
        self._stream = stream
        self._playing = True
        self._last_callback = time.monotonic()
        try:
            stream.start()
        except Exception:
            self.pause()
            raise

    def replace_buffer(self, audio):
        """Switch a remix at the current transport position and crossfade at the next callback."""
        if not self._playing or self._source is None:
            return False
        source = np.asarray(audio, dtype=np.float32)
        if source.ndim == 1:
            source = source[:, None]
        if source.shape != self._input_shape:
            return False
        self._input = source
        if self._source.shape[1] < source.shape[1]:
            source = source.mean(axis=1, keepdims=True)
        self._source = source
        return True

    def pause(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            except sd.PortAudioError:
                pass  # Invalidated devices may already have closed their stream.
            finally:
                try:
                    stream.close()
                except sd.PortAudioError:
                    pass
        self._playing = False
        self._source = None
        self._input = None
        self._input_shape = None
        self._region = self._last_callback = None

    def stop(self):
        self.pause()
        self._cursor = 0

    close = stop
