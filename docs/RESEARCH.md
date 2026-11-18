# 工程基线与技术选型

2026-11-18 在 Windows 11 Pro x64（10.0.26300）检查。启动时工作目录没有文件，Git 未初始化，没有代码、依赖清单、构建、DSP、模型接口、持久化、测试或安装配置可复用。系统有 .NET SDK 10.0.404、VS Build Tools、Python 3.11 和 3.14、Inno Setup 6，PATH 中没有独立 FFmpeg/ffprobe。项目采用独立 Python 3.11 环境，使用 Qt Widgets 桌面事件循环。选择依据是 NumPy/SciPy 可直接处理波形，PyAV 可携带解码器，ONNX Runtime 可在同一进程使用 NumPy 推理缓冲区。

## 逐项核查

日期为核查当日 GitHub 接口返回的默认分支最后提交的 UTC 日期。链接指向实际读取的源码快照。日期反映该仓库的提交情况，模型文件与预训练数据另有来源及条款。

| 项目和源码 | 维护快照 | 实现与依赖 | Windows、加速与集成决定 |
|---|---|---|---|
| [JUCE Oversampling](https://github.com/juce-framework/JUCE/blob/d60b7a78030661574a615b586d9325ba7a7fa7dd/modules/juce_dsp/processors/juce_Oversampling.cpp) | 11-02 | C++ 模板支持多级升采样、滤波和降采样。JUCE 9 模块为 AGPLv3 或商业 EULA。 | 可用 MSVC 构建，CPU DSP；本项目已有 Qt 主循环，未引入 JUCE。 |
| [FFmpeg loudnorm](https://github.com/FFmpeg/FFmpeg/blob/3a78197c4c969e7a493956733b340b68dcdb7fa0/libavfilter/af_loudnorm.c) | 11-18 | 滤镜依赖 ebur128 电平状态和动态增益控制，编码、重采样分别归 libavcodec、libswresample。授权取决于编译选项，主体 LGPL-2.1+，某些组合涉及 GPL 或 nonfree。 | PyAV wheel 内共享 DLL 承担 CPU 解码、重采样与编码；GPU 视频功能对音频母带用途无帮助。 |
| [Demucs apply_model](https://github.com/facebookresearch/demucs/blob/e976d93ecc3865e5757426930257e200846a520a/demucs/apply.py) | 2023-11-16，归档 | PyTorch tensor 分段、重叠加权重组、bag of models；实现 MIT。 | CPU 和 CUDA 支持依赖 PyTorch 构建。借鉴分段限内存思想，避免在普通安装中增加整套 PyTorch。 |
| [Ultimate Vocal Remover 分离调度](https://github.com/Anjok07/ultimatevocalremovergui/blob/a5f88453bfb2b38b05a965bcf67727243e0cbf19/separate.py) | 10-06 | 分别调用 Demucs、MDX/ONNX 与 VR 流程，依赖 NumPy、Torch 等。README 声明代码 MIT，本次根目录 LICENSE 链接不可读。 | Windows GUI 和多种后端说明，实际 CPU/GPU 路由随模型变化。按权重的发布者、哈希及说明单独审查。 |
| [Rubber Band Stretcher API](https://github.com/breakfastquay/rubberband/blob/e4296ac80b1170018a110bc326fd0d45a0eb27d6/rubberband/RubberBandStretcher.h) | 2025-02-27 | C++ 将离线分析、实时输入、延迟与 formant 选项区分；批处理程序还用 libsndfile。GPL-2.0+ 或商业许可。 | Windows CPU；未链接该库，项目音高修正能力以自有引擎验收为准。 |
| [librosa pitch](https://github.com/librosa/librosa/blob/76f10b8d2d00870fed47b4698927a4e7e78d1fb4/librosa/core/pitch.py) | 11-14 | NumPy/SciPy、Numba；YIN 使用短时差分及候选选择，pYIN 增加概率与时序连续性。ISC 许可。 | Windows CPU，运行不需要 CUDA。复用已有数组栈可以减少打包体积，借鉴有声区置信度设计。 |
| [aubio YIN](https://github.com/aubio/aubio/blob/ad5cf975aed08cc4562dd008cf9f83b12b82ffb8/src/pitch/pitchyin.c) | 04-10 | C 逐滞后计算差分后归一化并寻找谷值，核心算法在 CPU 上执行；解码、FFT 等依构建选择后端。GPL-3.0+。 | 可为 Windows 构建。用于比较音高算法，没有分发该实现。 |
| [RNNoise 帧处理](https://github.com/xiph/rnnoise/blob/70f1d256acd4b34a572f999a05c87bf00b67730d/src/denoise.c) | 2025-02-22 | C 在固定长度帧上高通→特征→神经网络频带增益→合成。BSD-3-Clause；训练模型及训练依赖与推理库分离。 | CPU、原生 SIMD。适合后续单声道语音链，当前通用立体声降噪用独立 DSP。 |
| [ONNX Runtime Python 源码](https://onnxruntime.ai/docs/api/python/modules/onnxruntime/capi/onnxruntime_inference_collection.html) | [PyPI 于 11-13 发布](https://pypi.org/project/onnxruntime/#history) | 源码把 GPU/CPU 映射到不同设备，InferenceSession 按 provider 初始化并支持回退。MIT，运行包内另带原生第三方许可。 | 本机采用 onnxruntime-directml 1.24.4。DirectML、CUDA 和 CPU 对应不同内核/依赖，检测到显卡或枚举到 provider 不足以说明模型推理成功。本次 GitHub API 和 raw 均返回 404，以官方 API 源码文档及实际 wheel 源文件交叉核验。 |
| [PyTorch CUDA 后端](https://github.com/pytorch/pytorch/blob/f2e0555046e9ffd90aaf091f3148422b18849760/torch/cuda/__init__.py) | 11-18 | Python 将设备可用性和延迟初始化委托 C++ 后端；CUDA 构建、驱动、依赖版本需匹配。BSD 风格主许可证含祖先项目版权。 | Windows CPU 和 CUDA 的候选训练/转换端；安装体积较大，标准分发仅需 ONNX 推理。 |
| [VST3 SDK 构建入口](https://github.com/steinbergmedia/vst3sdk/blob/3cdf9ca5d1f5b1b21e0a86832aa4abe55607bd96/CMakeLists.txt) | 08-11 | C++/CMake 构建接口、public.sdk、可选宿主示例和插件。该快照 LICENSE.txt 为 MIT，VST 商标规则另行适用。 | Windows x64 支持，CPU/GPU 由具体插件决定。现有处理链不依赖第三方 VST，不分发商业插件。 |
| [Audacity CMake](https://github.com/audacity/audacity/blob/b1c8dbe10d09f7a0d94cdd35b5ef9dc879278fb9/CMakeLists.txt) | 11-18 | 桌面构建将 Muse 框架、源模块、资源和测试分开；工程主许可 GPLv3，个别模块有独立许可。 | Windows 本地多轨 DAW，参考录音引用、渲染与轨道编辑分离的工作流；未复制软件界面或引擎。 |

## 直接运行依赖

- Qt for Python 6.12 / Shiboken6 使用 Qt Core、Gui、Widgets 的原生窗口、绘制、信号槽，由 CPU 线程池承担离线工作。安装包应保留 Qt 的许可证、通知和用户替换所分发动态库的能力。模块范围与分发要求可查 [Qt 官方许可](https://doc.qt.io/qtforpython-6/licenses.html)。
- PyAV 18.1.0 的重采样器封装 FFmpeg 重采样滤镜，Python 包许可证 BSD-3-Clause。通过 ctypes 查询包内 avcodec-62 DLL 得到 LGPL version 3 or later，构建配置同时包含 libmp3lame、libopus、libx264、libx265，av.libs 也确有 x264/x265 DLL。发布时需按实际捆绑的编解码器逐一核对。详见 [PyAV 源码](https://github.com/PyAV-Org/PyAV/blob/264c428119ecac10a2ef6bae62b50898a0bbca65/av/audio/resampler.py) 和 [FFmpeg 许可说明](https://github.com/FFmpeg/FFmpeg/blob/3a78197c4c969e7a493956733b340b68dcdb7fa0/LICENSE.md)。
- NumPy 2.4.6 与 SciPy 1.17.1 的 float32 数组、滤波器、傅里叶变换及统计承担离线 CPU DSP。二者含 BSD 及第三方数值库许可，Windows wheel 可直接使用。见 [NumPy 源码](https://github.com/numpy/numpy/blob/f7fdace610a999f8babe4d3be21e1ed855aaf478/numpy/lib/_function_base_impl.py) 和 [SciPy 频谱估计](https://github.com/scipy/scipy/blob/d4f15000d32a91c46515f4aba6959c619a3160ba/scipy/signal/_spectral_py.py)。
- sounddevice 0.5.6 使用 CFFI 包装 PortAudio；播放回调消费已经解码的数据，输出延迟依设备、主机 API 和缓冲大小变化。Python 封装为 MIT，Windows wheel 所含 PortAudio 二进制另需保留通知。见 [源码](https://github.com/spatialaudio/python-sounddevice/blob/dea905f65bfd3c3ad666f1628c8ea9921a96e149/src/sounddevice.py)。
