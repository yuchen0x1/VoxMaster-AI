# 0.4.0 自动化与兼容验证报告

## 当前实际环境

- 本轮实际工具宿主为 **ZCode Windows 本机环境**。任务书中的 DeepSeek Harness / `gpt-6.1-sol` 并非本会话可选工具设置，本轮没有伪称切换模型或平台。
- Windows 11 专业版 x64，Build 26300；AMD Ryzen 9 8945HX（32 逻辑处理器），系统报告 79.2 GiB RAM；RTX 5060 Laptop GPU 8,151 MiB，驱动 610.62。
- 系统 `python` 是 3.8.6，实际运行使用仓库 `.venv/Scripts/python.exe` **3.11.18**。PyAV 18.1.0，ONNX Runtime 提供 CPU / DirectML，未安装 PyTorch / CUDA execution provider。
- Git 与 GitHub 读取正常；`origin/main` 与本地基线 `36b4520` 一致。GitHub 身份有 ADMIN 权限，但没有执行远程写入、提交、推送或发布。分支为 `feat/voxmaster-0.4.0`，未覆盖用户修改。
- 本地文件写入、终端、NumPy/SciPy/PyAV、pytest、网络官方资料读取、原生 Windows UI、PyInstaller、MSYS2 与 Inno Setup 均已实际可用。浏览器/桌面能力有过短暂断线，原生界面通过重新连线和应用自身截图验证。

## 测试结果

| 阶段 | 结果 | 时间 / 证据 |
|---|---|---|
| 修改前全量基线 | **187 通过、3 跳过、0 失败、0 错误**（190） | 61.678 s；`.audit/040-baseline/pytest.xml` |
| 新增工作流首轮全量 | 355 通过、3 跳过（358） | 124.479 s；`.audit/040-post/full.xml`；隔离数据目录没带 CLI 模型路径的两项跳过已纠正并复跑 |
| 修复 CLI 权重注入后 | 365 通过、1 跳过（366） | 106.869 s；`.audit/040-post/final.xml` |
| **最终全量（含事务/隐私/发布保护修复）** | **436 通过、1 跳过、0 失败、0 错误（437）** | **212.295 s**；`.audit/040-release-review/shipped.xml` |
| 指纹/原子发布/长尾/多轨回放专项 | 12 通过、0 跳过 | `.audit/040-post/transactions.xml` |
| 原生 Qt 截图验证 | 成功，错误数组为空 | `docs/evidence-040/ui.json`；授权 FLEURS + 合成伴奏，不代表真实歌曲音质；最终代码复测 `.audit/040-release-review/ui-native/` |
| 代码编译/版本一致性/Ruff F 检查 | 通过 | `compileall`、`scripts/version.py`（0.4.0）、`ruff check --select F --ignore F841` |
| 冻结 Windows 应用自检 | PASS（真实 DirectML、WAV/MP3/FLAC/AAC） | `.audit/040-release-review/freeze-verified.txt` 与隔离构建 `build/bundle-*.json` |
| 推送后 GitHub Actions 四平台回归 | **全部 success**：Windows、Ubuntu 24.04、macOS 15、macOS 15 Intel，actionlint 作业亦通过 | run [44751308841](https://github.com/yuchen0x1/VoxMaster-AI/actions/runs/44751308841)；runner 环境不等于 Windows 10 实机验收 |
| 冻结专用 CLI 实际歌曲链路 | 成功，CPU provider，FLEURS 真人夹具→FLAC | `.audit/040-release-review/frozen-song/report.json`；首次误加 `--cli` 前缀被参数解析器拒绝，已更正命令并重跑 |
| 两首完整真人歌曲 | 本地推理/渲染/编码/回读通过 | [AUDIO-040.md](AUDIO-040.md)；**主观听审待验收**；最终媒体事务代码复测 `.audit/040-release-review/real/`，输出哈希与首轮一致 |
| 最终冻结专用 CLI 实际歌曲链路 | 成功，CPU provider，FLEURS 真人夹具→FLAC | `.audit/040-release-review/frozen-song/report.json`（`--cli` 前缀误用已记录更正） |
| 隔离安装/便携/0.3.2→0.4.0 升级/卸载 | **PASS**，旧设置/恢复工程/录音哈希不变 | `.audit/040-release-review/installation-final.txt` 与 `build/accept-e98a35fa-09f5-43ee-bc01-31656a003f36/`（最终交付包复测）；唯一 AppId，不替换生产安装 |
| 最终冻结产物暴露面复测 | 83/C；PE-SIGN、PACK-PYI 不变，无新增/加重 | `.audit/040-release-review/exposure-shipped.json`；不是安全认证 |

### 唯一最终跳过

`test_report_rejects_symbolic_link_alias`：当前 Windows 账户无创建文件符号链接权限（WinError 1314）。没有提升权限或修改系统设置。硬链接、同路径、大小写/Unicode 别名、报告与素材/成品/模型配置/断点文件冲突均已执行测试。此跳过不计入通过。

### 运行最终全套的方法

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
$env:VOX_MODEL_TEST_WEIGHTS = "$env:LOCALAPPDATA\VoxMasterAI\models\spleeter-2stems-7001ba31"
$env:VOXMASTER_DATA = "$PWD\.audit\recheck-data"
.\.venv\Scripts\python.exe -X faulthandler -m pytest -q -rs --junitxml=.audit\recheck.xml
```

模型目录必须已经合法获取且含两个固定 SHA-256 的 ONNX 文件；测试不会下载。没有模型时对应真实推理用例会真实跳过，不伪装通过。

## 回归覆盖与修复

- 真实 DSP：旧 18 风格、音高/尾音、压缩/EQ、母带顺序、波形/频谱/等响监听、CLI 安全、多轨撤销及工程恢复的原测试保留。
- 三模式：导入前选择、工程记录、切换不丢参数/输出、整曲确认与可编辑参数、重新分离的明确确认。
- 整曲：保守人声链、伴奏增益/EQ、既有 Studio 混音、最终母带一次、峰值与有限值检查。标准/增强母带只改 LUFS 或峰值时保留算法强度。
- 内容指纹：原音与双轨 SHA-256；即使大小与 mtime 一样，替换媒体会重解码并使旧分离证据失效。哈希是素材身份核对，不是模型效果或文件真实性认证。
- 事务：分离发布前取消清理暂存；发布后的晚到取消交付已完成结果；恢复记录写入失败保留旧会话/历史。新增分轨同目录恢复工程，真实 CPU 整曲结果在主恢复盘故障后仍可精确重开，错误提示包括恢复路径；同目录工程写入失败不发布任何分轨。
- 读取期间变更：在解码前与成品复测阶段替换同尺寸、同 mtime 的素材，提交前复验必须拒绝，不继续使用旧 verified 来源。
- 非破坏：旧 v1 项目、可选字段、相对路径、历史备份、新方案精确回放；带非中性分轨与真实 Studio 编辑的保存/重开输出逐采样相同；外部分轨允许不同尾长且保留伴奏结尾。
- 模型：真实 CPU 推理、真实 DirectML 推理进程故障恢复、断点传输与哈希失败路径；断点传输单元测试可模拟 HTTP，但核心歌曲验收使用真实权重与采样。
- 私有媒体：源码归档过滤全部媒体/模型，仅允许固定哈希的 CC BY 4.0 FLEURS 夹具；隐私路径与替换夹具拒绝测试。

## 失败透明记录

没有删除失败测试。开发途中新增 GUI 测试出现夹具错误与未返回确认值引起模态挂起，已停止本任务启动的测试进程、修正夹具并重跑。一次新 CLI 证据测试因隔离目录没有显式权重路径失败，已改为传入既有合法权重，之后全量通过。早期 Qt `offscreen` 截图出现缺字方框，未用于 README；改用原生 Windows Qt 平台重新运行并人工检查图像，最终截图中文正常。冻结 CLI 首次参数错误没有输出音频，已用正确语法重跑。

## 尚未覆盖

- Windows 10 实机、Linux/macOS 实体设备本轮 runner 之外的环境、NVIDIA CUDA / DirectML 以外设备没有新验收。四平台 GitHub Actions 回归通过只证明该 runner 上源码测试通过，不沿用为实体机或安装包验收。
- 没有实体音频设备拔插、跨实体高 DPI 屏、真实低延迟播放性能、长音频连续压力/磁盘耗尽新数据。
- 未执行人工听审，不能用自动通过证明“音质优秀”“专业母带完成”或“模型分离效果优秀”。
- 安装/便携/升级/卸载结果单列 [DELIVERY-040.md](DELIVERY-040.md)，不与源码或离屏 GUI 测试混算。