# 参与开发

使用 Python 3.11 创建独立环境并安装 `requirements.txt`。Windows 使用 DirectML 包；Linux/macOS 使用 CPU ONNX Runtime。Linux 需系统 PortAudio、EGL，macOS 需 PortAudio。请先阅读 [架构](docs/ARCHITECTURE.md) 和 [平台决策](docs/PLATFORMS.md)。

`main` 为发布分支，短期开发使用 `codex/*`、`feature/*` 或 `fix/*`。通过 PR 合并，冲突在开发分支解决，禁止强制推送 main。每次修改说明影响平台、旧工程兼容和未验证项。功能不适用某平台时解释原因。

验证：`python scripts/version.py`、`ruff check --select F --ignore F841 vox app.py`、`python -m pytest -q`。无显示环境设置 `QT_QPA_PLATFORM=offscreen`；始终设置 `VOXMASTER_DATA` 到临时目录。真实模型测试需设置 `VOX_MODEL_TEST_WEIGHTS`，未配置会跳过两项。测试样本授权见 tests/fixtures/README.md。

版本来源是 `vox/__init__.py`，用 `python scripts/version.py --set X.Y.Z` 同步 Windows 资源。更新 README 最新更新、CHANGELOG 与 docs/releases/release-notes.md。正式标签只能指向经审查并通过 CI 的 main 提交。发布命令和恢复办法见 [发布维护](docs/MAINTENANCE.md)。

本仓库尚无整仓开源许可证。贡献、代码再分发和授权需先与作者确认；研究第三方实现不会自动授予本项目其许可证。请勿提交私人录音、模型权重、证书或密钥。
