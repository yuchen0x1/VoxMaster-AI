"""Pinned Spleeter weights, resumable transfers and local storage."""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import shutil
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QLockFile

REVISION = "7001ba316a615cacddb3f9ef3ec416661a277e26"
REPOSITORY = "csukuangfj/sherpa-onnx-spleeter-2stems"
BASE = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}"
FILES = {
    "vocals.onnx": (39318336, "bdc16ab6bf6117ddd4842c19e80e40e2be188fc555295064d424616b0224ac97"),
    "accompaniment.onnx": (
        39318343,
        "671ace17acd3720674a2bc14de32ac6292453dec20d9eb0ba4255d4ad8e3d8c0",
    ),
}
SIZE = sum(size for size, _ in FILES.values())
FOLDER = "spleeter-2stems-" + REVISION[:8]
BLOCK = 256 * 1024


def app_data():
    from .platforms import data_directory

    return data_directory()


def settings():
    try:
        data = json.loads((app_data() / "model-center.json").read_text("utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def save_settings(**changes):
    base = app_data()
    base.mkdir(parents=True, exist_ok=True)
    with locked(base, "model-config"):
        cfg = settings()
        cfg.update(changes)
        with tempfile.NamedTemporaryFile(dir=base, mode="w", encoding="utf-8", delete=False) as tmp:
            json.dump(cfg, tmp, ensure_ascii=False)
        Path(tmp.name).replace(base / "model-center.json")


def directory():
    return Path(settings().get("directory") or app_data() / "models") / FOLDER


@contextmanager
def locked(directory, name="model-manager"):
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / (name + ".lock")))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        raise RuntimeError("此模型正在使用，请等待当前模型任务结束。")
    try:
        yield
    finally:
        lock.unlock()


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("任务已停止")


def size_of(path):
    return path.stat().st_size if path.is_file() else 0


def digest(path, cancel=None):
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while data := f.read(BLOCK):
            check_cancel(cancel)
            hasher.update(data)
    return hasher.hexdigest()


def verify(root=None, cancel=None):
    root = root or directory()
    for name, (size, sha) in FILES.items():
        path = root / name
        if size_of(path) != size or digest(path, cancel) != sha:
            raise ValueError(f"{name} 缺失或校验失败，请在模型中心下载或修复。")


def transfer(url, part, size, sha, cancel, progress):
    """Reject wrong ranges and restart safely when an origin ignores Range."""
    for attempt in range(3):
        check_cancel(cancel)
        offset = size_of(part)
        if offset == size and digest(part, cancel) == sha:
            return
        if offset >= size:
            part.unlink()
            offset = 0
        headers = {"User-Agent": "VoxMasterAI/1", "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=25) as response:
                if response.status == 206:
                    match = re.fullmatch(
                        r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", "")
                    )
                    if not match or int(match[1]) != offset or int(match[3]) != size:
                        raise ValueError("服务器返回了无效的断点续传范围")
                elif response.status == 200:
                    offset = 0
                else:
                    raise ValueError(f"模型下载失败 · HTTP {response.status}")
                with part.open("ab" if offset else "wb") as output:
                    while data := response.read(BLOCK):
                        check_cancel(cancel)
                        offset += len(data)
                        if offset > size:
                            raise ValueError("模型长度超过目录记录值")
                        output.write(data)
                        progress(offset)
            if offset != size:
                raise OSError("模型传输中断")
            if digest(part, cancel) != sha:
                part.unlink(missing_ok=True)
                raise ValueError("模型 SHA-256 校验失败")
            return
        except InterruptedError:
            raise
        except (OSError, ValueError, http.client.HTTPException):
            if attempt == 2:
                raise
            if cancel is None:
                time.sleep(attempt + 1)
            elif cancel.wait(attempt + 1):
                check_cancel(cancel)


def install(cancel, progress, force=False, root=None):
    root = root or directory()
    with locked(root):
        completed = 0
        staged = []
        for name, (size, sha) in FILES.items():
            check_cancel(cancel)
            path = root / name
            part = root / (name + ".part")
            if force or part.exists() or size_of(path) != size or digest(path, cancel) != sha:
                transfer(
                    f"{BASE}/{name}?download=true",
                    part,
                    size,
                    sha,
                    cancel,
                    lambda count: progress((completed + count) / SIZE, f"下载 {name}"),
                )
                staged.append((part, path))
            completed += size
        # Preserve an installed version during a refresh. Cancel discards only
        # staged files, including complete downloads awaiting their partner.
        check_cancel(cancel)
        for part, path in staged:
            part.replace(path)
        verify(root, cancel)
        progress(1, "模型已校验并安装")


def remove(root=None, partial=False):
    root = root or directory()
    with locked(root):
        for name in FILES:
            (root / (name + ".part")).unlink(missing_ok=True)
            if not partial:
                (root / name).unlink(missing_ok=True)


def migrate(new_base, cancel):
    src = directory().resolve()
    dst = (Path(new_base) / FOLDER).resolve()
    if src == dst:
        return
    if src in dst.parents or dst in src.parents:
        raise ValueError("请选择独立的模型目录")
    with locked(src), locked(dst):
        if any((src / (n + ".part")).exists() for n in FILES):
            raise ValueError("请先完成或取消下载，再迁移模型。")
        assets = [n for n in FILES if (src / n).is_file()]
        for name in assets:
            sha = FILES[name][1]
            source = src / name
            target = dst / name
            if digest(source, cancel) != sha:
                raise ValueError(f"{name} 校验失败，请先修复下载。")
            if target.exists():
                if digest(target, cancel) != sha:
                    raise ValueError(f"目标位置已有不同内容的 {name}")
                continue
            with tempfile.NamedTemporaryFile(dir=dst, delete=False) as file:
                tmp = Path(file.name)
            try:
                shutil.copyfile(source, tmp)
                if digest(tmp, cancel) != sha:
                    raise ValueError("迁移校验失败")
                tmp.replace(target)
            finally:
                tmp.unlink(missing_ok=True)
        save_settings(directory=str(dst.parent))
        for name in assets:
            (src / name).unlink()
