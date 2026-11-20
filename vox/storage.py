"""Versioned, non-destructive project and preference storage."""

import copy
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from .platforms import data_directory

ROOT = data_directory()
PROJECT_EXT = ".voxproj"


def size_limit(path):
    return (256 if Path(path).suffix.lower() == PROJECT_EXT else 16) * 1024**2


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        value,
        ensure_ascii=False,
        indent=None if path.suffix.lower() == PROJECT_EXT else 2,
        allow_nan=False,
    ).encode("utf-8")
    if len(body) > size_limit(path):
        raise ValueError(f"文件超过可保存大小 {size_limit(path) // 1024**2} MiB。")
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path):
    if Path(path).stat().st_size > size_limit(path):
        raise ValueError(f"文件超过可读取大小 {size_limit(path) // 1024**2} MiB。")
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def preferences():
    try:
        data = read_json(ROOT / "settings.json")
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def project(source="", name="未命名工程"):
    return dict(
        version=1,
        name=name,
        source=str(source),
        reference="",
        style="经典喊麦",
        params={},
        applied=False,
        studio=None,
        stems={},
        history=[],
        kind="自动判断",
    )


def _string_mapping(value, field):
    if not isinstance(value, dict):
        raise ValueError(f"工程字段 {field} 必须是对象。")
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError(f"工程字段 {field} 必须是字符串到字符串映射。")
    return value


def _validate_project_data(data):
    # Optional legacy fields remain supplied by project(); validate only their
    # established types so version-1 files with omitted fields stay compatible.
    for field in ("name", "source", "reference", "style", "kind"):
        if not isinstance(data[field], str):
            raise ValueError(f"工程字段 {field} 必须是字符串。")
    if not isinstance(data["params"], dict):
        raise ValueError("工程字段 params 必须是对象。")
    if not isinstance(data["applied"], bool):
        raise ValueError("工程字段 applied 必须是布尔值。")
    if not isinstance(data["history"], list) or any(
        not isinstance(item, str) for item in data["history"]
    ):
        raise ValueError("工程字段 history 必须是字符串数组。")
    _string_mapping(data["stems"], "stems")
    if data["studio"] is not None:
        if not isinstance(data["studio"], dict):
            raise ValueError("工程字段 studio 必须是对象或 null。")
        external = data["studio"].get("external_sources", {})
        _string_mapping(external, "studio.external_sources")
    if "before_reference" in data and not isinstance(data["before_reference"], dict):
        raise ValueError("工程字段 before_reference 必须是对象。")
    if "mode" in data and data["mode"] not in ("vocal", "song", "multitrack"):
        raise ValueError("未知的工作台模式。")
    if data.get("song") is not None:
        from .song import validate_plan

        data["song"] = validate_plan(data["song"])
        if not all(data["stems"].get(key) for key in ("Vocal", "Instrumental")):
            raise ValueError("歌曲方案需要人声与伴奏两条分轨。")
    if "separation" in data and not isinstance(data["separation"], dict):
        raise ValueError("工程字段 separation 必须是对象。")


def load_project(path):
    raw = read_json(path)
    if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("source"), str):
        raise ValueError("无法读取该工程版本。")
    data = project()
    data.update(raw)
    _validate_project_data(data)
    for field in ("source", "reference"):
        if data[field]:
            data[field] = str((Path(path).parent / data[field]).resolve())
    data["stems"] = {
        key: str((Path(path).parent / val).resolve()) for key, val in data["stems"].items()
    }
    if data.get("studio"):
        ext = data["studio"].get("external_sources", {})
        data["studio"]["external_sources"] = {
            key: str((Path(path).parent / val).resolve()) for key, val in ext.items()
        }
    return data


def save_project(path, data, backup=True):
    path = Path(path).resolve()
    if path.suffix.lower() != PROJECT_EXT:
        raise ValueError("工程文件需要使用 .voxproj 扩展名。")
    raw = copy.deepcopy(data)

    def relative(value):
        try:
            return os.path.relpath(value, path.parent) if value else ""
        except ValueError:  # Separate Windows drive.
            return str(value)

    for field in ("source", "reference"):
        raw[field] = relative(data[field])
    raw["stems"] = {key: relative(val) for key, val in data["stems"].items()}
    if raw.get("studio"):
        ext = raw["studio"].get("external_sources", {})
        raw["studio"]["external_sources"] = {key: relative(val) for key, val in ext.items()}
    if path.exists() and backup:
        old = read_json(path)
        if not isinstance(old, dict) or old.get("version") != 1 or "source" not in old:
            raise ValueError("目标位置已有其他文件，请更换工程名称。")
        folder = path.parent / (path.name + ".history")
        write_json(
            folder / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + PROJECT_EXT),
            data_at_location(old, path.parent, folder),
        )
    write_json(path, raw)


def data_at_location(raw, before, after):
    """Rebase media references between the old and new containing directories."""
    after = Path(after).resolve()
    result = copy.deepcopy(raw)

    def move(ref):
        if not ref:
            return ""
        absolute = (before / ref).resolve()
        try:
            return os.path.relpath(absolute, after)
        except ValueError:  # Separate Windows drive.
            return str(absolute)

    for key in ("source", "reference"):
        result[key] = move(result.get(key, ""))
    result["stems"] = {key: move(value) for key, value in result.get("stems", {}).items()}
    if result.get("studio"):
        ext = result["studio"].get("external_sources", {})
        result["studio"]["external_sources"] = {key: move(value) for key, value in ext.items()}
    return result
