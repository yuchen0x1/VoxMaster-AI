"""Workstation paths, audio routing, machine inventory and opt-in update checks."""

import json
import queue
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from packaging.version import Version
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .hardware import resolve_output
from .theme import manager as theme_manager, normalize_mode, set_status


_CHECK_DEADLINE = 30
_CHECK_MAX_BYTES = 65536


def _valid_url(url):
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not (parsed.username or parsed.password)
        )
    except ValueError:
        return False


def _check_cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("检查已取消。")


def check_version(url, cancel=None):
    if not _valid_url(url):
        raise ValueError("请输入不含账号信息的 HTTPS 清单地址。")
    deadline = time.monotonic() + _CHECK_DEADLINE

    def checkpoint():
        _check_cancelled(cancel)
        if time.monotonic() >= deadline:
            raise TimeoutError("更新清单检查超时，请稍后重试。")

    checkpoint()
    with requests.get(
        url,
        headers={"Accept": "application/json"},
        allow_redirects=False,
        stream=True,
        timeout=(4, 8),
    ) as response:
        checkpoint()
        if response.status_code != 200:
            raise ValueError(f"服务器返回 HTTP {response.status_code}，请使用清单的直接地址。")
        headers = getattr(response, "headers", {})
        content_length = headers.get("Content-Length")
        if content_length is not None:
            try:
                content_length = int(content_length)
            except (TypeError, ValueError) as exc:
                raise ValueError("更新清单长度无效。") from exc
            if content_length < 0:
                raise ValueError("更新清单长度无效。")
            if content_length > _CHECK_MAX_BYTES:
                raise ValueError("更新清单超过 64 KiB。")
        data = bytearray()
        for block in response.iter_content(8192):
            checkpoint()
            data.extend(block)
            if len(data) > _CHECK_MAX_BYTES:
                raise ValueError("更新清单超过 64 KiB。")
        checkpoint()
    checkpoint()
    try:
        manifest = json.loads(data)
    except (TypeError, ValueError) as exc:
        raise ValueError("更新清单不是有效 JSON。") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("version"), str):
        raise ValueError("更新清单需要字符串字段 version。")
    latest = Version(manifest["version"])
    if latest > Version(__version__):
        return f"此清单报告有新版本 {latest}。本机版本为 {__version__}。"
    return f"本机版本 {__version__}。此清单当前提供的版本为 {latest}。"


def _label(text, role="sub"):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.PlainText)
    label.setObjectName(role)
    return label


class SettingsDialog(QDialog):
    def __init__(self, settings, report, parent=None):
        super().__init__(parent)
        self._settings = settings.copy()
        self._report = report or {}
        self.setWindowTitle("设备与设置")
        self.setMinimumSize(600, 460)
        self.resize(715, 536)
        self._paths = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tabs.addTab(self._inventory(), "设备报告")
        self.tabs.addTab(self._preferences(), "音频与目录")
        self.tabs.addTab(self._updates(), "软件更新")
        self._theme_preview = theme_manager()
        self._theme_before = self._theme_preview.mode
        self._preview_mode = None
        self.finished.connect(self._restore_theme_preview)
        self.tabs.addTab(self._appearance(), "外观")
        self.error = _label("")
        self.error.setAccessibleName("设置状态")
        self.error.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存设置")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText("关闭")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _inventory(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_label("本机音频环境", "section"))
        layout.addWidget(
            _label(
                "音频分析与调音使用 CPU。人声分离可在模型中心选择运算设备，模型在显卡运行失败时会回退 CPU。"
            )
        )
        tree = QTreeWidget()
        tree.setHeaderLabels(["设备与资源", "检测结果"])
        tree.setAlternatingRowColors(False)
        tree.setRootIsDecorated(True)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        layout.addWidget(tree, 1)
        r = self._report
        if not r:
            tree.addTopLevelItem(QTreeWidgetItem(["设备报告", "等待环境检测完成后重新打开设置。"]))
            return page

        def row(name, value, parent=None):
            item = QTreeWidgetItem([name, str(value) if value is not None else "未检测到"])
            item.setToolTip(1, item.text(1))
            if parent is not None:
                parent.addChild(item)
            else:
                tree.addTopLevelItem(item)
            return item

        row("操作系统", r.get("system"))
        cpu = row("处理器", r.get("cpu"))
        row(
            "物理核心 / 逻辑线程",
            f"{r.get('physical_cores') or '—'} / {r.get('logical_cores') or '—'}",
            cpu,
        )
        row("物理内存", f"{r['ram_gib']:.1f} GiB" if r.get("ram_gib") else None)
        row(
            "用户目录可用空间",
            f"{r['free_disk_gib']:.1f} GiB" if r.get("free_disk_gib") is not None else None,
        )
        dedicated = {item["name"]: item for item in r.get("nvidia", [])}
        for chip in r.get("gpus", []):
            gpu = row("显示适配器", chip["Name"])
            gpu_info = dedicated.get(chip["Name"], {})
            row("驱动版本", gpu_info.get("driver", chip.get("DriverVersion")), gpu)
            if "vram_mib" in gpu_info:
                row(
                    "显存总量 / 可用",
                    f"{gpu_info['vram_mib']} / {gpu_info['free_vram_mib']} MiB",
                    gpu,
                )
            gpu.setExpanded(bool(gpu_info))
        row("CUDA 运行库", r.get("cuda_runtime"))
        devices = r.get("devices", [])
        for field, key, name in (
            ("inputs", "default_input", "音频输入"),
            ("outputs", "default_output", "音频输出"),
        ):
            group = [dev for dev in devices if dev[field]]
            default = next((dev for dev in group if dev["id"] == r.get(key)), None)
            parent = row(name, default["name"] if default else f"{len(group)} 个端点")
            for dev in group:
                row(dev["host"], f"{dev['name']} · {dev[field]} ch", parent)
        libs = r.get("runtimes", {})
        lib_group = row("本地运行库", f"{len(libs)} 项")
        for name, val in libs.items():
            row(name, val, lib_group)
        for message in r.get("errors", []):
            row("检测提示", message)
        return page

    def _preferences(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_label("试听输出", "section"))
        self.output = QComboBox()
        self.output.setAccessibleName("试听音频输出设备")
        self.output.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.output.setMinimumContentsLength(20)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output, 1)
        refresh = QPushButton("刷新设备")
        refresh.clicked.connect(self._rescan)
        output_row.addWidget(refresh)
        layout.addLayout(output_row)
        self._populate_devices(self._settings)
        layout.addSpacing(14)
        layout.addWidget(_label("文件位置", "section"))
        form = QFormLayout()
        for key, label, hint in (
            ("project_dir", "工程", "默认文档目录"),
            ("export_dir", "成品", "默认导出目录"),
            ("cache_dir", "音频缓存", "系统临时目录"),
        ):
            editor = QLineEdit(str(self._settings.get(key) or ""))
            editor.setPlaceholderText(hint)
            editor.setClearButtonEnabled(True)
            editor.setAccessibleName(label + "目录")
            select = QPushButton("浏览…")
            select.setAccessibleName(f"浏览{label}目录")
            select.clicked.connect(lambda _, e=editor, title=label: self._browse(e, title))
            row = QHBoxLayout()
            row.addWidget(editor, 1)
            row.addWidget(select)
            form.addRow(label, row)
            self._paths[key] = editor
        layout.addLayout(form)
        layout.addWidget(_label("较长录音的解码缓存在释放音轨时自动清理。新目录对下一次导入生效。"))
        layout.addStretch()
        return page

    def _populate_devices(self, settings):
        self.output.clear()
        self.output.addItem("跟随系统默认输出", None)
        self._outputs = {d["id"]: d for d in self._report.get("devices", []) if d["outputs"]}
        for i, item in self._outputs.items():
            self.output.addItem(f"{item['name']}  ·  {item['host']}", i)
        selected = resolve_output(settings, self._report)
        if selected is not None:
            self.output.setCurrentIndex(self.output.findData(selected))

    def _rescan(self):
        from . import hardware, playback

        selected = self.value()
        try:
            if not playback.refresh_endpoints():
                raise RuntimeError("请先停止工作台和混音台的试听，再刷新设备。")
            devices = hardware.devices()
            input_id, output_id = map(int, hardware.sd.default.device)
            self._report.update(devices=devices, default_input=input_id, default_output=output_id)
            self._populate_devices(selected)
            old = self.tabs.widget(0)
            self.tabs.removeTab(0)
            self.tabs.insertTab(0, self._inventory(), "设备报告")
            old.deleteLater()
            self.error.setText(f"已重新检测到 {len(self._outputs)} 个输出端点。")
            set_status(self.error, "info")
        except Exception as exc:
            self.error.setText(str(exc))
            set_status(self.error, "error")
        self.error.show()

    def _browse(self, editor, title):
        path = QFileDialog.getExistingDirectory(
            self, f"选择{title}目录", editor.text() or str(Path.home())
        )
        if path:
            editor.setText(path)

    def _appearance(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = _label("外观主题", "section")
        layout.addWidget(heading)
        layout.addWidget(_label(
            "选择浅色、深色，或跟随操作系统的外观设置。更改会立即预览；取消或关闭时恢复进入设置前的外观。"
        ))
        self.theme_choice = QComboBox()
        self.theme_choice.setAccessibleName("外观主题")
        self.theme_choice.addItem("跟随系统", "system")
        self.theme_choice.addItem("浅色", "light")
        self.theme_choice.addItem("深色", "dark")
        current = normalize_mode(self._settings.get("theme", "system"))
        self.theme_choice.setCurrentIndex(self.theme_choice.findData(current))
        self.theme_choice.currentIndexChanged.connect(self._preview_theme)
        layout.addWidget(self.theme_choice)
        self._theme_preview_hint = _label("外观主题会应用于工作台、自绘图形、混音台与对话框。")
        layout.addWidget(self._theme_preview_hint)
        layout.addStretch()
        return page

    def _preview_theme(self, _index):
        if not hasattr(self, "theme_choice"):
            return
        self._preview_mode = self.theme_choice.currentData()
        self._theme_preview.set_mode(self._preview_mode)

    def _restore_theme_preview(self, result):
        if not result and self._preview_mode is not None:
            self._theme_preview.set_mode(self._theme_before)

    def _updates(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_label(f"VoxMaster AI  {__version__}", "section"))
        official = QPushButton('检查并安装官方更新…')
        official.clicked.connect(self._official_update)
        layout.addWidget(official)
        layout.addWidget(
            _label("官方更新使用签名清单校验。下方自定义清单仅用于查询版本，不参与下载和安装。")
        )
        self.url = QLineEdit(self._settings.get("update_url", ""))
        self.url.setPlaceholderText("HTTPS 更新清单地址")
        self.url.setAccessibleName("更新清单地址")
        layout.addWidget(self.url)
        layout.addWidget(_label("清单格式示例  " + json.dumps({"version": __version__})))
        self.check = QPushButton("检查版本")
        self.check.clicked.connect(self._check)
        layout.addWidget(self.check, alignment=Qt.AlignLeft)
        self.update_status = _label("")
        layout.addWidget(self.update_status)
        layout.addStretch()
        self._messages = queue.SimpleQueue()
        self._check_cancel = None
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self.finished.connect(self._cancel_check)
        return page

    def _official_update(self):
        from .dialogs import managed_dialog
        from .update_dialog import UpdateDialog

        with managed_dialog(UpdateDialog(self.parent())) as dialog:
            dialog.exec()

    def _check(self):
        if self._check_cancel is not None:
            return
        url = self.url.text().strip()
        if not _valid_url(url):
            self.update_status.setText("请输入 HTTPS 清单的直接地址。")
            return
        self.check.setEnabled(False)
        self.update_status.setText("正在读取更新清单…")
        messages = self._messages
        cancel = threading.Event()
        self._check_cancel = cancel

        def run():
            # The worker only retains plain Python state, never a Qt widget.
            try:
                result = check_version(url, cancel)
            except InterruptedError:
                result = "检查已取消。"
            except Exception as exc:
                result = f"检查失败。{exc}"
            messages.put((cancel, result))

        try:
            threading.Thread(target=run, daemon=True).start()
        except RuntimeError as exc:
            self._check_cancel = None
            self.check.setEnabled(True)
            self.update_status.setText(f"检查失败。{exc}")
            return
        self._timer.start()

    def _cancel_check(self, _result=None):
        if self._check_cancel is not None:
            self._check_cancel.set()
            self._check_cancel = None
            self.update_status.setText("检查已取消。")
        self._timer.stop()
        self.check.setEnabled(True)

    def _poll(self):
        while True:
            try:
                cancel, result = self._messages.get_nowait()
            except queue.Empty:
                return
            # A closed/reopened dialog must never consume an old request's result.
            if cancel is not self._check_cancel or cancel.is_set():
                continue
            self._check_cancel = None
            self._timer.stop()
            self.check.setEnabled(True)
            self.update_status.setText(result)
            return

    def value(self):
        values = self._settings.copy()
        for key, editor in self._paths.items():
            text = editor.text().strip()
            if text:
                values[key] = str(Path(text).expanduser().resolve())
            else:
                values.pop(key, None)
        if "devices" in self._report:
            values["output_device"] = self.output.currentData()
            device = self._outputs.get(values["output_device"], {})
            values["output_device_name"] = device.get("name")
            values["output_device_host"] = device.get("host")
        values["update_url"] = self.url.text().strip()
        if hasattr(self, "theme_choice"):
            values["theme"] = self.theme_choice.currentData()
        return values

    def accept(self):
        try:
            values = self.value()
            if values["update_url"] and not _valid_url(values["update_url"]):
                raise ValueError("更新清单需要 HTTPS 地址。")
            for key in self._paths:
                if key in values:
                    path = Path(values[key])
                    path.mkdir(parents=True, exist_ok=True)
                    with tempfile.TemporaryFile(dir=path):
                        pass
        except (OSError, ValueError, RuntimeError) as exc:
            self.error.setText(f"设置未保存。{exc}")
            set_status(self.error, "error")
            self.error.show()
            return
        super().accept()
