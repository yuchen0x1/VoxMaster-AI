"""Read-only, offline hardware inventory; recommendations require actual execution."""

import csv
import ctypes
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import av
import sounddevice as sd

device_lock = threading.RLock()


def devices():
    with device_lock:
        hostapis = sd.query_hostapis()
        return [
            dict(
                id=i,
                name=item["name"],
                host=hostapis[item["hostapi"]]["name"],
                inputs=item["max_input_channels"],
                outputs=item["max_output_channels"],
                default_rate=item["default_samplerate"],
            )
            for i, item in enumerate(sd.query_devices())
        ]


def resolve_output(settings, inventory):
    """PortAudio indices can change on hot-plug or reboot."""
    index = settings.get("output_device")
    if index is None:
        return None
    name, host = settings.get("output_device_name"), settings.get("output_device_host")
    outputs = [d for d in inventory.get("devices", []) if d.get("outputs", 0)]
    if name and host:
        matches = [d["id"] for d in outputs if (d["name"], d["host"]) == (name, host)]
        return index if index in matches else next(iter(matches), None)
    return index if any(d["id"] == index for d in outputs) else None


def _run(command):
    process = subprocess.run(
        command,
        capture_output=True,
        timeout=12,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if process.returncode:
        raise RuntimeError(f"{Path(command[0]).name} 返回 {process.returncode}")
    return process.stdout.decode("utf-8-sig", errors="replace").strip()


def _cuda_runtime():
    names = []
    toolkit = (
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "NVIDIA GPU Computing Toolkit"
        / "CUDA"
    )
    names.extend(toolkit.glob("v*/bin/cudart64*.dll"))
    names.extend(toolkit.glob("v*/bin/x64/cudart64*.dll"))
    for base in sys.path:
        if Path(base).name == "site-packages":
            names.extend(Path(base).glob("nvidia/cuda_runtime/bin/cudart64*.dll"))
    for path in sorted(names, reverse=True):
        try:
            runtime = ctypes.WinDLL(str(path))
            ver = ctypes.c_int()
            if runtime.cudaRuntimeGetVersion(ctypes.byref(ver)) == 0:
                return f"{ver.value // 1000}.{(ver.value % 1000) // 10}"
        except (AttributeError, OSError):
            continue
    return None


def report():
    result = dict(
        system=platform.platform(),
        architecture=platform.machine(),
        cpu=platform.processor(),
        logical_cores=os.cpu_count(),
        free_disk_gib=round(shutil.disk_usage(Path.home()).free / 2**30, 1),
        ram_gib=None,
        physical_cores=None,
        gpus=[],
        nvidia=[],
        devices=[],
        recommended_mode="CPU",
        cuda_runtime=None,
        errors=[],
    )
    libs = {"Python": platform.python_version(), "PortAudio": sd.get_portaudio_version()[1]}
    libs.update({k: ".".join(map(str, v)) for k, v in av.library_versions.items()})
    for pkg in (
        "av",
        "numpy",
        "scipy",
        "sounddevice",
        "pyside6-essentials",
        "onnxruntime",
        "onnxruntime-gpu",
        "onnxruntime-directml",
    ):
        try:
            libs[pkg] = version(pkg)
        except PackageNotFoundError:
            continue
    result["runtimes"] = libs
    try:
        result["devices"] = devices()
        result["default_input"], result["default_output"] = map(int, sd.default.device)
    except (sd.PortAudioError, OSError, ValueError) as exc:
        result["errors"].append(f"音频设备：{exc}")
    if os.name != "nt":
        return result
    system32 = Path(os.environ["SystemRoot"]) / "System32"
    ps = system32 / "WindowsPowerShell/v1.0/powershell.exe"
    script = """
    $ErrorActionPreference='Stop'
    [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
    $processors=@(Get-CimInstance Win32_Processor)
    $computer=Get-CimInstance Win32_ComputerSystem
    $windows=Get-CimInstance Win32_OperatingSystem
    $display=@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,AdapterRAM)
    [pscustomobject]@{ cpu=($processors.Name -join ' / '); cores=($processors |
       Measure-Object -Sum NumberOfCores).Sum; ram=$computer.TotalPhysicalMemory;
       system=$windows.Caption+' '+$windows.Version; gpus=$display } | ConvertTo-Json -Depth 4 -Compress
    """
    try:
        info = json.loads(_run([str(ps), "-NoProfile", "-NonInteractive", "-Command", script]))
        result.update(
            system=info["system"],
            cpu=info["cpu"].strip(),
            physical_cores=int(info["cores"]),
            ram_gib=round(info["ram"] / 2**30, 1),
            gpus=info["gpus"],
        )
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result["errors"].append(f"Windows 硬件信息：{exc}")
    smi = system32 / "nvidia-smi.exe"
    if smi.is_file():
        try:
            inventory = _run(
                [
                    str(smi),
                    "--query-gpu=name,memory.total,memory.free,driver_version",
                    "--format=csv,noheader,nounits",
                ]
            )
            for name, total, free, driver in csv.reader(
                io.StringIO(inventory), skipinitialspace=True
            ):
                result["nvidia"].append(
                    dict(name=name, vram_mib=int(total), free_vram_mib=int(free), driver=driver)
                )
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            result["errors"].append(f"NVIDIA 驱动：{exc}")
    result["cuda_runtime"] = _cuda_runtime()
    return result
