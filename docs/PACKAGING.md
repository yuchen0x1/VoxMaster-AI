# 构建与 Windows 安装验证

构建机使用 Windows 11 x64、CPython 3.11.18 x64、MSYS2 UCRT64 GCC 与 Inno Setup 6。双击程序无需另外安装 Python、Qt、FFmpeg CLI、GPU SDK 或模型。

## 重建

在 PowerShell 项目根目录执行下列命令。开发环境使用 PyPI 的 PyAV wheel。分发包在 staging 阶段改用源码构建的音频专用 FFmpeg 8.1.2 动态库。Windows 安装 MSYS2 UCRT64 工具链，默认 Bash 路径为 C:\msys64\usr\bin\bash.exe，也可通过 -Bash 指定。

```powershell
uv python install 3.11.18
uv venv --python 3.11.18 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.\scripts\build.ps1
.\scripts\verify-release.ps1
```

build.ps1 构建 PyInstaller 目录版，修正 PyAV 的 DLL 导入名，复制许可文件，运行实包诊断，然后创建便携 ZIP、Inno 安装包和源代码 ZIP。首次构建从 FFmpeg 和 MSYS2 下载固定散列的源码及工具。在运行环境里替换 FFmpeg 动态库时使用相同 ABI 主版本和 DLL 名。Qt 的对应源码可用下列命令单独准备。

```powershell
.\.venv\Scripts\python.exe packaging\qt_sources.py
```

verify-release.ps1 从发布 ZIP 实际解压，在隔离目录实际安装、启动程序诊断并卸载。检查 Windows 安装记录消失，压缩包与安装包各自成功处理、编码及解码音频。当前账号如已有正式版，脚本从两版源码包取出原始 Inno 配方，解压各自的成品负载，按同一随机值隔离 AppId 与开始菜单组，随后在独立注册项与目录下执行升级验收并核对正式注册信息。使用干净账号时可直接测试原封安装程序。

两个脚本可传入 -ModelDirectory，参数为同时含 vocals.onnx 和 accompaniment.onnx 的完整模型目录。启用后，运行时在独立进程上实际完成分离并记录使用的 provider。模型缺席时基础诊断照常运行。

## 0.1.1 升级安装复测

首次 0.1.0 的四件发布物和校验清单位于本地 dist/archive/0.1.0。验证脚本先检查当前账号已有安装项，随后在合适的注册空间内将旧版安装到独立测试目录。旧版实际导入真人普通话 WAV 并写出用户设置与恢复工程。文件持久化后中断旧进程，随后在同目录安装新版，用安装版与便携版分别打开旧工程、重新解码并检查录音、设置、工程的哈希。卸载结束后复查系统登记和用户数据。

```powershell
.\scripts\verify-release.ps1 -PreviousInstaller .\dist\archive\0.1.0\VoxMasterAI-Setup.exe -ModelDirectory <两份模型所在目录>
```

0.1.1 的可执行文件、安装程序资源与 Windows 卸载记录使用同一产品版本。构建时使用 PyInstaller 清理项目专属缓存并重新分析应用。旧版的稳定 AppId 用于识别覆盖安装。构建和素材验收并行时，也可先用 -Phase Freeze 生成并实测可执行目录，待文档齐备用 -Phase Package 同步文档、生成发布物。后者核对应用源码、依赖锁、资源和可执行文件散列，保证源码包与已冻结程序对应。

## 0.1.1 冻结程序与安装验收

2026-11-18，Windows 11 Pro x64 10.0.26300。检测到当前用户已有正在使用的 0.1.0。测试在独立安装目录和用户数据目录内执行。两版 Inno 安装配方使用相同的隔离 AppId，最终包复测同时隔离开始菜单组，并使用对应发行物的实际程序负载。正式安装实例保持运行。正式 AppId 的原封安装包覆盖现有用户版本，仍需在单独的 Windows 测试账号验证。

| 检查 | 状态和实测结果 |
|---|---|
| 清洁编译和运行库 | PASS。清理项目 PyInstaller 缓存，重建 x64 EXE。包内可读取 av 18.1.0、NumPy 2.4.6、SciPy 1.17.1、sounddevice 0.5.6、PySide6 Essentials 6.12.0、ONNX Runtime DirectML 1.24.4 的实际发行元数据。 |
| 同目录覆盖升级与异常恢复 | PASS（隔离 AppId）。0.1.0 安装程序落盘后，启动旧版导入 10.38 秒真人普通话。恢复记录与设置落盘后，异常终止专属旧进程。覆盖安装新版后，两份发行负载均按旧工程重新解码 457,758 帧，恢复「经典喊麦」和用户导入目录。 |
| 双形态实际音频处理 | PASS。安装和便携应用都通过 PyAV 调用项目自建 FFmpeg 8.1.2，在空白临时目录实际编码并回读 WAV、MP3、FLAC、AAC。2 秒测试信号的处理前后差值 RMS 为 0.05087。 |
| 实包 GPU 推理 | PASS。DirectML 双模型实际执行，应用记录 RTX 5060 Laptop、推理进程显存 567 MiB。CUDA 测试在独立源码运行时进行，详见 [硬件兼容性报告](COMPATIBILITY-011.md)。 |
| 正常启动与退出 | PASS。启动冻结程序的普通 GUI 入口，传入 FLEURS 原声。只有在该进程生成工程恢复记录并创建主窗口后，向该窗口发送正常关闭请求，退出码 0。 |
| 卸载与数据保留 | PASS（隔离 AppId）。两个版本的系统登记按预期切换，卸载后测试注册项与 EXE 消失。工程、旧版设置和音频 SHA-256 均保持原值，正式安装版本与目录未变。 |

候选验收另发现 Inno 的 /NOICONS 参数在 0.1.0 配方下未隔离开始菜单目录。候选安装和卸载使用同名组，用户原有快捷方式随测试卸载被移除。根据原安装 unins000.dat 记录恢复了该快捷方式，并读回确认目标为用户原安装目录的 VoxMasterAI.exe。用户安装程序及工程未被覆盖。最终验收脚本改用每次独立的开始菜单组，追加正式快捷方式文件散列与正式注册信息的前后核验。

安装位置、裸 Win10 和人工听感的验收范围详见专项报告。实测数据含冻结的 EXE SHA-256 与双份应用的测量结果。[升级实测数据](evidence-011/package-upgrade.json)

## 0.1.0 本机验证基线

- PASS · Windows 11 Pro x64，无开发运行时的 PATH。安装后和便携版都通过 WAV、MP3、FLAC、AAC 编码与再次解码，Qt 建立 Windows 平台上下文，PortAudio 初始化成功。222 Hz 的可控测试信号仅用于诊断，真实录音测试另见音频验收报告。
- PASS · 两种形式均由独立推理进程完成 DirectML 分离，NVIDIA GeForce RTX 5060 Laptop GPU 观测到 567 MiB 进程显存。两条输出轨在 10⁻⁶ 精度内重建输入。
- PASS · 安装后可执行文件存在，卸载完成后程序及注册项消失。未安装到既有用户程序目录。
- PASS · 使用 Open Computer Use 检查正常启动的打包程序。导入 FLEURS 真人普通话文件，主窗口显示 16 kHz、单声道、32 bit、10.38 秒。点击「AI 一键调音」后读回的综合响度由 −42.2 变为 −15.6 LUFS，真峰值 −1.2 dBTP。
- Windows 10 真机和全新虚拟机兼容性仍需实测。当前 Windows 包为未签名本地构建。SHA256SUMS.txt 供检查传输完整性。

## 发布物

| 文件 | 内容 |
| --- | --- |
| dist/VoxMasterAI-Setup.exe | 仅当前用户安装，可在系统应用列表卸载 |
| dist/VoxMasterAI-Portable.zip | 解压到普通目录，启动 VoxMasterAI.exe |
| dist/VoxMasterAI-Source.zip | 工程、完整源码、脚本、测试、录音署名和文档 |
| dist/Qt-6.12.0-Corresponding-Sources.zip | 对应 QtBase、QtSvg、QtImageFormats、Qt for Python 源码 |
| dist/SHA256SUMS.txt | 三个交付压缩包及安装程序的 SHA-256 |

安装包与便携版包含 FFmpeg 和 LAME 对应源码及构建配置。未捆绑大型分离模型、ASIO SDK、x264 和 x265。使用的许可证、对应源码和运行库授权见 [第三方清单](THIRD_PARTY.md)。


Windows 10 实机复测需要能进入的目标系统。当前 Windows 11 账号能查询 Hyper-V 管理服务运行状态，枚举来宾时系统拒绝访问，未发现可用 VMware 或 VirtualBox 客户端。Qt 6.12 官方列出的 x64 起点为 Windows 10 1809，对应安装器要求的构建 17763。兼容性结论以实际来宾和硬件测试为准。[Qt 6.12 Windows 平台矩阵](https://doc.qt.io/qt-6.12/windows.html)
