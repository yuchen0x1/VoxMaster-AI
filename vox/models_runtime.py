"""Local two-stem inference. Native inference runs in a disposable process."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from scipy import fft, signal

from . import models_store as store

NFFT, HOP, FRAMES, BINS = 4096, 1024, 512, 1024
CONTEXT = 32
STRIDE = (FRAMES - 2 * CONTEXT) * HOP
CROSSFADE = 16 * HOP
FADE_IN = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, CROSSFADE))).astype("f")[:, None]
WINDOW = signal.windows.hann(NFFT, sym=False).astype("f")


def _spectrum(audio, pos):
    # The model sees context on both sides of every output block.
    length = HOP * (FRAMES - 1) + NFFT
    left = pos - CONTEXT * HOP
    right = min(len(audio), left + length)
    first = max(0, left)
    segment = np.zeros((2, length), dtype=np.float32)
    segment[:, first - left : right - left] = audio[first:right].T
    frames = np.lib.stride_tricks.sliding_window_view(segment, NFFT, axis=1)[:, ::HOP]
    return fft.rfft(frames * WINDOW, axis=-1)


def _synthesize(spec, mask, length):
    spec[:, :, BINS:] = 0
    spec[:, :, :BINS] *= mask
    frames = fft.irfft(spec, n=NFFT, axis=-1) * WINDOW
    block = np.zeros((2, (FRAMES - 1) * HOP + NFFT), dtype=np.float32)
    # Four interleaved rectangular blocks overlap at each output sample.
    for i in range(NFFT // HOP):
        start = i * HOP
        block[:, start : start + FRAMES * HOP] += frames[:, :, start : start + HOP].reshape(2, -1)
    start = CONTEXT * HOP
    return (block[:, start : start + length].T / 1.5).astype("f")


def _gpu_usage():
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if res.returncode == 0 and res.stdout.strip():
            return (
                " · NVIDIA 整卡显存 " + res.stdout.strip().splitlines()[0].replace(", ", "/") + " MiB"
            )
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def _memory_usage():
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes

    class ProcessMemory(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak",
                "working",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
            )
        ]

    counters = ProcessMemory()
    counters.size = ctypes.sizeof(counters)
    if ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.c_void_p(-1), ctypes.byref(counters), counters.size
    ):
        return f" · 推理进程 {counters.working // 1048576} MiB"
    return ""


def _infer_worker(conn, root, provider, temp_root):
    adapter = None
    dll_handles = []
    try:
        import onnxruntime as ort

        if provider == "CUDAExecutionProvider" and os.name == "nt" and hasattr(ort, "preload_dlls"):
            from importlib.metadata import PackageNotFoundError, distribution

            # cuDNN loads additional engine plugins on first convolution. ORT's
            # eager DLL list does not cover all newer cuDNN 9 plugins.
            for package in ("nvidia-cudnn-cu12", "nvidia-cudnn-cu13"):
                try:
                    bin_dir = distribution(package).locate_file("nvidia/cudnn/bin")
                except PackageNotFoundError:
                    continue
                if bin_dir.is_dir():
                    dll_handles.append(os.add_dll_directory(str(bin_dir)))
                    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            ort.preload_dlls()
        if provider == "DmlExecutionProvider":
            from .models_dxgi import DirectMLAdapter

            adapter = DirectMLAdapter()
        options = {"device_id": str(adapter.index)} if adapter else {}
        if provider == "CUDAExecutionProvider":
            options = {"device_id": "0", "cudnn_conv_algo_search": "HEURISTIC", "use_tf32": "0"}
            if os.name == "nt":
                from .models_dxgi import cuda_adapter

                adapter = cuda_adapter(0)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            models = []
            for name in store.FILES:
                opt = ort.SessionOptions()
                opt.log_severity_level = 3
                opt.intra_op_num_threads = min(4, os.cpu_count() or 1)
                opt.add_free_dimension_override_by_name("num_splits", 1)
                if provider != "CPUExecutionProvider":
                    opt.enable_mem_pattern = False
                    opt.enable_profiling = True
                    opt.profile_file_prefix = str(Path(tmp) / name)
                sess = ort.InferenceSession(
                    str(root / name), sess_options=opt, providers=[(provider, options)]
                )
                if sess.get_providers()[0] != provider:
                    raise RuntimeError("运行库未加载所选加速器")
                # Own retries in the parent, so a runtime's internal CPU retry
                # cannot silently be reported as a successful GPU execution.
                sess.disable_fallback()
                models.append(sess)
            conn.send(("ready", None))
            first = True
            while True:
                tensor = conn.recv()
                if tensor is None:
                    return
                power = []
                for model in models:
                    out = model.run(None, {model.get_inputs()[0].name: tensor})[0]
                    if out.shape != tensor.shape or not np.isfinite(out).all():
                        raise ValueError("模型返回无效频谱")
                    power.append(np.square(out[:, 0, :, :]))
                    if first and provider != "CPUExecutionProvider":
                        trace = json.loads(Path(model.end_profiling()).read_text("utf-8"))
                        if not any(e.get("args", {}).get("provider") == provider for e in trace):
                            raise RuntimeError("实际模型未在所选 GPU 上执行")
                first = False
                mask = (power[0] + 5e-11) / (power[0] + power[1] + 1e-10)
                stats = _memory_usage()
                if adapter:
                    stats += adapter.stats()
                elif provider != "CPUExecutionProvider":
                    stats += _gpu_usage()
                conn.send(("ok", (mask, stats)))
    except (EOFError, BrokenPipeError):
        pass
    except Exception as exc:
        try:
            conn.send(("error", str(exc)))
        except (OSError, EOFError):
            pass
    finally:
        if adapter:
            adapter.close()
        for handle in dll_handles:
            handle.close()
        conn.close()


class Worker:
    def __init__(self, root, provider):
        ctx = mp.get_context("spawn")
        self.conn, child = ctx.Pipe()
        # Parent owns profiling scratch even when a driver crashes the child.
        self.scratch = tempfile.TemporaryDirectory(prefix="vox-ort-")
        self.process = ctx.Process(
            target=_infer_worker, args=(child, root, provider, self.scratch.name), daemon=True
        )
        try:
            self.process.start()
        except BaseException:
            self.conn.close()
            self.scratch.cleanup()
            raise
        finally:
            child.close()

    def result(self, cancel, kind):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            store.check_cancel(cancel)
            if self.conn.poll(0.1):
                msg, value = self.conn.recv()
                if msg != kind:
                    raise RuntimeError(str(value))
                return value
            if not self.process.is_alive():
                raise RuntimeError(f"推理进程已退出 ({self.process.exitcode})")
        raise TimeoutError("模型推理超时")

    def close(self):
        self.conn.close()
        self.process.join(0.3)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(3)
        self.process.close()
        self.scratch.cleanup()


def providers(mode):
    import onnxruntime as ort

    available = ort.get_available_providers()
    options = {
        "CUDA": ["CUDAExecutionProvider"],
        "DirectML": ["DmlExecutionProvider"],
        "CPU": [],
        "auto": ["CUDAExecutionProvider", "DmlExecutionProvider"],
    }
    return [p for p in options.get(mode, []) if p in available] + ["CPUExecutionProvider"]


def separate(audio, sr, cancel=None, progress=None, *, root=None, mode=None, audit=None):
    progress = progress or (lambda fraction, message: None)
    audio = np.asarray(audio, dtype=np.float32)
    if sr != 44100 or audio.ndim != 2 or audio.shape[1] != 2 or not audio.shape[0]:
        raise ValueError("分离需要 44.1 kHz 双声道音频")
    if not np.isfinite(audio).all():
        raise ValueError("音频包含无效样本")
    root = root or store.directory()
    mode = mode or store.settings().get("mode", "auto")
    candidates = iter(providers(mode))
    provider = next(candidates)
    fallback = ""
    if mode in ("CUDA", "DirectML") and provider == "CPUExecutionProvider":
        fallback = f"{mode} 运行库不可用，使用 CPU · "
    vocal = np.empty_like(audio)
    overlap = None
    worker = None
    used = []
    try:
        with store.locked(root):
            store.verify(root, cancel)
            for pos in range(0, len(audio), STRIDE):
                store.check_cancel(cancel)
                spec = _spectrum(audio, pos)
                tensor = np.ascontiguousarray(np.abs(spec[:, None, :, :BINS]))
                while True:
                    try:
                        if worker is None:
                            progress(pos / len(audio), fallback + "加载 " + provider)
                            worker = Worker(root, provider)
                            worker.result(cancel, "ready")
                        worker.conn.send(tensor)
                        mask, stats = worker.result(cancel, "ok")
                        break
                    except InterruptedError:
                        raise
                    except (RuntimeError, OSError, EOFError, TimeoutError) as exc:
                        previous = provider
                        provider = next(candidates, None)
                        if provider is None:
                            raise RuntimeError(f"{previous} 推理失败 · {exc}") from exc
                        if worker:
                            worker.close()
                            worker = None
                        fallback = f"{previous} 不可用，已回退 · "
                count = min(STRIDE, len(audio) - pos)
                # The two independently inferred masks can disagree at a cut.
                # Blend the shared audio using complementary raised cosines.
                window = _synthesize(spec, mask, min(count + CROSSFADE, len(audio) - pos))
                if overlap is not None:
                    n = len(overlap)
                    window[:n] = window[:n] * FADE_IN[:n] + overlap * (1 - FADE_IN[:n])
                vocal[pos : pos + count] = window[:count]
                overlap = window[count:].copy()
                if provider not in used:
                    used.append(provider)
                progress((pos + count) / len(audio), fallback + provider + stats)
        if audit is not None:
            audit["providers"] = used
        return vocal, audio - vocal
    finally:
        if worker is not None:
            worker.close()
