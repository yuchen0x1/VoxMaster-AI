# 第三方软件及再分发说明

适用于 VoxMaster AI 0.4.0 Windows x64 本机构建。安装目录 ThirdParty 保存 wheel 随附的许可证、版权声明、嵌套组件声明及版本元数据。requirements.txt 同时锁定运行、测试和打包工具。应用自有代码按仓库根目录 [MIT LICENSE](../LICENSE) 授权，第三方组件、模型和媒体不因此变更许可。

0.4.0 **未新增运行依赖、模型权重、商业 SDK 或第三方源代码**。新歌曲流程只组合已有 NumPy / SciPy DSP、PyAV、ONNX Runtime 与 Qt；未复制竞品实现。详见 [竞品与四层许可研究](RESEARCH-040.md)。模型条款不明确的组件继续按需获取，不随发行包分发权重。

| 组件 | 作用及授权来源 |
| --- | --- |
| CPython 3.11.18 | PSF License 及 Python-LICENSE.txt 所列历史与标准库第三方许可。|
| Qt 6.12、PySide6 Essentials、Shiboken6 | Qt Widgets 原生界面。使用开源 LGPLv3 选项，保留可替换的 DLL、PySide6 绑定及 LGPL/GPL 文本。Qt 内嵌的 ICU、图像、字体与压缩库另有第三方声明。|
| NumPy、SciPy | BSD-3-Clause。wheel 中还含 OpenBLAS、LAPACK、运行库与其他第三方组件，各包 LICENSE 与附属文件列出正文。|
| PyAV 18.1.0 | BSD-3-Clause。分发包的 PyAV 扩展导入表已恢复标准 FFmpeg ABI DLL 名称，以便更换编解码库。|
| FFmpeg 8.1.2 | 本包从官方源构建共享库，LGPL-2.1-or-later。配置、源码压缩包、许可证和构建脚本随包提供。支持本地文件、音频解码、滤镜与编码。|
| LAME 3.100、winpthreads | MP3 编码器 LGPL，带对应 MSYS2 源码包。winpthreads 版权与例外见 COPYING.winpthreads。|
| python-sounddevice、PortAudio | MIT 系列许可。分发 Windows x64 常规 PortAudio 动态库，支持系统音频设备。|
| ONNX Runtime DirectML 1.24.4 | ONNX Runtime 为 MIT，内嵌依赖详见 ThirdPartyNotices。DirectML.dll 1.15.4 另适用 Microsoft DirectML 许可。|
| Microsoft Visual C++ Runtime、UCRT | 来自 Windows/Python/Qt 的运行库，按 Microsoft 可再分发代码条款使用。|
| requests、urllib3、certifi、charset-normalizer、idna、cffi、pycparser、protobuf、flatbuffers、packaging | HTTP、证书、外部函数与模型运行环境。各自版本及 Apache-2.0、MIT、MPL-2.0、BSD 等适用条款见 ThirdParty/Python 中相应目录。|
| PyInstaller、Inno Setup | PyInstaller bootloader 的 GPL 例外允许分发打包程序。Inno Setup 按其随附许可生成 Windows 安装、卸载程序。测试工具 pytest 等留在开发环境。|

应用随附的 LGPL 动态库允许以 ABI 兼容的修改版代换及为调试这些修改而逆向。替换前先退出应用，在便携目录的 _internal 下保留导出符号、DLL 名和体系结构。Qt、PySide 和 Shiboken 的对应源码可按版本从 Qt 官方归档获取。重新发布时应一并提供各 LGPL 组件的对应源码获取途径、版权文本和适用修改说明。

- [Qt 官方源码归档](https://download.qt.io/archive/qt/6.12/6.12.0/single/)
- [PySide 官方版本标签](https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.12.0)
- [Qt 第三方组件说明与授权](https://doc.qt.io/qt-6/licenses-used-in-qt.html)
- [FFmpeg 源码与授权条件](https://ffmpeg.org/legal.html)
- [PyAV 源码与版本](https://github.com/PyAV-Org/PyAV/tree/v18.1.0)
- [MSYS2 LAME 源码包](https://repo.msys2.org/mingw/sources/mingw-w64-lame-3.100-3.src.tar.zst)
- [DirectML 官方包和许可](https://www.nuget.org/packages/Microsoft.AI.DirectML/1.15.4)
- [Microsoft Visual C++ 可再分发条款](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files)
- [ONNX Runtime 许可与第三方声明](https://github.com/microsoft/onnxruntime/tree/v1.24.4)
- [PyInstaller 许可](https://pyinstaller.org/en/stable/license.html)

模型按需下载。模型权重、转换产物和测试音频的许可见模型中心及对应验证文档。正式公开发布前还需确认发行人的微软分发资格、Qt 对应源码供应及音频编码专利在发行地域的适用情况。

## 0.1.1 测试素材与推理后端

- Google FLEURS 普通话录音按 CC BY 4.0 使用。源码测试样本的原文件名、作者、修改情况及散列见 tests/fixtures/README.md。[原始数据说明](https://huggingface.co/datasets/google/fleurs)
- VocalSet 1.1 为 Julia Wilkins、Prem Seetharaman、Alison Wahl 与 Bryan Pardo 发布的真人演唱录音。第三方署名与许可为 CC BY 4.0，专项脚本按 ZIP 成员记录原名与散列。源文件由使用者运行测试获取。[VocalSet 1.1 固定发布记录](https://zenodo.org/records/1203819)
- 八条 Freesound 验收样本按各自发布页的 CC0 1.0 标注本地使用。作品 ID、署名、原页和文件散列位于源码 tests/mc_corpus/sources.json，录音与受控重混保存在本机验收目录。[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)
- 本地用户指定的商用录音和听审输出留在验收目录。型号为 Spleeter 的两份权重由模型中心单独获取；当前推理运行时包含 DirectML 和 CPU，独立 CUDA 验证环境与正式打包运行时分别记录。[模型来源和授权](MODELS.md)
