# 上游研究、差距与实施决定

观察时间：2026-11-18T14:21:14.834170+00:00。证据为 GitHub API 实际返回；Stars/Forks 是该时点快照。逐仓读取 README、根目录、一个主源码/构建入口、最新提交、前三个开放 Issue 和最新 Release。这是结构抽查，不是对每个项目的全部代码审计。原始字段和失败请求保留在 [upstreams.json](evidence-020/upstreams.json)。NOASSERTION/null 表示 API 无法判定许可，不能解释为没有许可或允许复制；本轮没有导入研究项目代码。

| 项目/证据 | 分类/技术 | Stars/Forks | 最近提交/活跃窗口 | 最新 Release | API 许可证 | 价值与决定 |
|---|---|---|---|---|---|---|
| [audacity/audacity](https://github.com/audacity/audacity/blob/b1c8dbe10d09f7a0d94cdd35b5ef9dc879278fb9/CMakeLists.txt) | 直接竞品 / C++ | 19101/2736 | 2026-11-18 / 30天内 | Audacity-4.0.2 | NOASSERTION | CMake 模块/测试边界；参考离线编辑与分析分离，不复制 GPL 界面/代码 |
| [Ardour/ardour](https://github.com/Ardour/ardour/blob/c453ffb46913eeefea24f740fc21f29cf51c15b6/wscript) | 直接竞品 / C++ | 5441/1029 | 2026-11-18 / 30天内 | 无公开 Release/请求未得结果 | NOASSERTION | waf 构建与专业会话；参考非破坏编辑，避免引入复杂实时路由 |
| [LMMS/lmms](https://github.com/LMMS/lmms/blob/6b00eab040d8d51320cbaab32f54f7584b5cfe00/CMakeLists.txt) | 相邻竞品 / C++ | 10686/1326 | 2026-11-16 / 30天内 | v1.3.0-alpha.2 | GPL-2.0 | CMake 与合成/编曲模块；完整 MIDI 编曲超出喊麦调音定位 |
| [musescore/MuseScore](https://github.com/musescore/MuseScore/blob/0b5a4994656a89a471de778cdfec369c282c49f1/CMakeLists.txt) | 相邻竞品 / C++ | 15440/3420 | 2026-11-18 / 30天内 | v4.7.7 | NOASSERTION | 大型桌面模块化与资源分层；谱面编辑不适用本轮 |
| [mixxxdj/mixxx](https://github.com/mixxxdj/mixxx/blob/dc4bf99322bb9a4c59483d24c2c40d1df2d1b726/CMakeLists.txt) | 相邻竞品 / C++ | 7413/2089 | 2026-11-14 / 30天内 | 2.5.6 | NOASSERTION | 桌面构建/设备适配；参考设备身份和回归矩阵，不做 DJ 曲库 |
| [tenacityteam/tenacity](https://github.com/tenacityteam/tenacity/blob/500a2d63b6cb1fc94aeccb09136b86899fa1b926/CMakeLists.txt) | 直接竞品 / C++ | 830/22 | 2026-11-17 / 30天内 | 无公开 Release/请求未得结果 | NOASSERTION | 桌面编辑器 CMake；参考可检查的文件编辑工作流 |
| [zrythm/zrythm](https://github.com/zrythm/zrythm/blob/c680fbad9265cbad578d6fda1ba251766e91edaa/CMakeLists.txt) | 直接竞品 / C++ | 3210/154 | 2026-11-14 / 30天内 | v2.0.0-alpha.8 | NOASSERTION | Qt/QML 与 CMake 演进，迁移不能只看旧版 Meson 文档；暂不迁移现有 Widgets |
| [surge-synthesizer/surge](https://github.com/surge-synthesizer/surge/blob/78f07b152a9ff55d9357ed0b1f3053bf5c123254/CMakeLists.txt) | 技术参考 / C | 4143/517 | 2026-11-17 / 30天内 | Nightly | GPL-3.0 | 跨平台原生音频构建；合成器功能不直接吸收 |
| [Anjok07/ultimatevocalremovergui](https://github.com/Anjok07/ultimatevocalremovergui/blob/a5f88453bfb2b38b05a965bcf67727243e0cbf19/separate.py) | 直接竞品 / Python | 27234/2094 | 2026-10-06 / 90天内 | v5.6 | MIT | 模型类型分支与分离调度；保留固定模型目录和可解释后端回退 |
| [facebookresearch/demucs](https://github.com/facebookresearch/demucs/blob/e976d93ecc3865e5757426930257e200846a520a/demucs/apply.py) | 技术参考 / Python | 10416/1682 | 2023-11-16 / 180天外，已归档 | 无公开 Release/请求未得结果 | MIT | apply_model 分块与重叠；仓库归档不等于不可参考，但不新增 Torch 打包负担 |
| [deezer/spleeter](https://github.com/deezer/spleeter/blob/6f2c8a2e283914faa544631430f65b793f1b1218/spleeter/separator.py) | 直接竞品 / Python | 28537/3048 | 2026-10-28 / 30天内 | v2.3.0 | MIT | separator 封装模型、音频适配器与会话；本项目继续使用单独下载 ONNX 权重 |
| [nomadkaraoke/python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator/blob/4dd3477c0a8f5bfb0fb053c6ed444bb935cb150e/audio_separator/separator/separator.py) | 直接竞品 / Python | 1497/214 | 2026-10-29 / 30天内 | v0.48.0 | MIT | 分离器门面与后端选择；模型授权仍须逐项审查 |
| [RVC-Project/Retrieval-based-Voice-Conversion-WebUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/81eed5e8f68b6bed1789f682fe78cdd324495afc/realtime_gui.py) | 相邻竞品 / Python | 39318/5364 | 2026-08-04 / 180天内 | 2.3.260718 | MIT | 实时 GUI 与推理边界；声线转换需另行授权及听审，延期 |
| [w-okada/voice-changer](https://github.com/w-okada/voice-changer/blob/7e2ce5c4800010bbc7604968bd29b802534fac05/server/voice_changer/VoiceChanger.py) | 相邻竞品 / Python | 21407/2462 | 2026-11-17 / 30天内 | 无公开 Release/请求未得结果 | NOASSERTION | 服务端 VoiceChanger 管线；实时变声不是离线调音的直接替代 |
| [xiph/rnnoise](https://github.com/xiph/rnnoise/blob/70f1d256acd4b34a572f999a05c87bf00b67730d/src/denoise.c) | 技术参考 / C | 5972/1090 | 2025-02-22 / 180天外 | v0.2 | BSD-3-Clause | 固定帧神经降噪；只列未来候选，保留现有立体声算法 |
| [breakfastquay/rubberband](https://github.com/breakfastquay/rubberband/blob/e4296ac80b1170018a110bc326fd0d45a0eb27d6/rubberband/RubberBandStretcher.h) | 技术参考 / C++ | 815/132 | 2025-02-27 / 180天外 | 无公开 Release/请求未得结果 | GPL-2.0 | 离线/实时伸缩 API、延迟与共振峰；GPL/商业授权需决定后再链接 |
| [rspeyer/soundtouch](https://github.com/rspeyer/soundtouch/blob/3fcb95810daeaf2f05726b4d7d150429e1753b0b/include/SoundTouch.h) | 技术参考 / C++ | 339/88 | 2016-05-05 / 180天外 | 无公开 Release/请求未得结果 | LGPL-2.1 | SoundTouch API 的节奏/音高分离；镜像活跃度需谨慎，不直接引入旧实现 |
| [aubio/aubio](https://github.com/aubio/aubio/blob/ad5cf975aed08cc4562dd008cf9f83b12b82ffb8/src/pitch/pitchyin.c) | 技术参考 / C | 3790/429 | 2026-04-10 / 180天外 | 0.4.9 | GPL-3.0 | YIN 谷值候选；GPL 不作为无许可证项目的可任意复制实现 |
| [librosa/librosa](https://github.com/librosa/librosa/blob/76f10b8d2d00870fed47b4698927a4e7e78d1fb4/librosa/core/pitch.py) | 技术参考 / Python | 9010/1135 | 2026-11-14 / 30天内 | 1.0.1 | ISC | 音高概率/连续性；继续以既有 NumPy/SciPy 栈降低依赖体积 |
| [spotify/basic-pitch](https://github.com/spotify/basic-pitch/blob/fa5997af0a8210982619003269994a1be25eddf3/basic_pitch/inference.py) | 技术参考 / Python | 6095/566 | 2025-11-13 / 180天外 | v0.4.0 | Apache-2.0 | 音符推理和模型加载；不将其演唱转 MIDI 能力伪装成本轮已实现 |
| [csteinmetz1/pyloudnorm](https://github.com/csteinmetz1/pyloudnorm/blob/b8d67bfd3ce5deef872f688fcfa491a0ca69fddd/pyloudnorm/meter.py) | 技术参考 / Python | 796/69 | 2026-01-04 / 180天外 | v0.2.0 | MIT | 门限响度测量；参考独立标定，保留原 LUFS 回归 |
| [FFmpeg/FFmpeg](https://github.com/FFmpeg/FFmpeg/blob/9aa0ad8985af33474929e8451b0e900d9f512cf2/libavfilter/af_loudnorm.c) | 技术参考 / C | 67541/14672 | 2026-11-18 / 30天内 | 无公开 Release/请求未得结果 | NOASSERTION | loudnorm 与编解码构建；保留音频专用 LGPL 动态库和源码义务 |
| [PyAV-Org/PyAV](https://github.com/PyAV-Org/PyAV/blob/264c428119ecac10a2ef6bae62b50898a0bbca65/av/audio/resampler.py) | 直接依赖 / Python | 3337/471 | 2026-11-16 / 30天内 | v19.0.2 | BSD-3-Clause | 重采样模块；运行 wheel 与发布编解码器必须分别核查 |
| [spatialaudio/python-sounddevice](https://github.com/spatialaudio/python-sounddevice/blob/dea905f65bfd3c3ad666f1628c8ea9921a96e149/src/sounddevice.py) | 直接依赖 / Python | 1286/165 | 2026-11-14 / 30天内 | 0.5.6 | MIT | PortAudio Python 封装；设备移除/索引变动不能只测默认设备 |
| [PortAudio/portaudio](https://github.com/PortAudio/portaudio/blob/8b6333ff8744b22afaa694bc4b8b22f6f0dba6dd/include/portaudio.h) | 直接依赖 / C | 2161/417 | 2026-11-13 / 30天内 | v19.7.0 | NOASSERTION | C API 与宿主后端；Linux/macOS 系统依赖进入 CI |
| [juce-framework/JUCE](https://github.com/juce-framework/JUCE/blob/d60b7a78030661574a615b586d9325ba7a7fa7dd/modules/juce_dsp/processors/juce_Oversampling.cpp) | 技术参考 / C++ | 9161/2242 | 2026-11-02 / 30天内 | 9.0.5 | NOASSERTION | 过采样处理器与原生音频生态；现有 Qt 主循环不替换为另一套框架 |
| [steinbergmedia/vst3sdk](https://github.com/steinbergmedia/vst3sdk/blob/3cdf9ca5d1f5b1b21e0a86832aa4abe55607bd96/CMakeLists.txt) | 技术参考 / CMake | 2401/238 | 2026-08-11 / 180天内 | 无公开 Release/请求未得结果 | MIT | SDK CMake 组件边界；插件沙箱、崩溃隔离与商标规则成本高，延期 |
| [pyinstaller/pyinstaller](https://github.com/pyinstaller/pyinstaller/blob/db739d431f2e90223333cb257068a766add5c1a8/PyInstaller/building/build_main.py) | 构建依赖 / Python | 13160/2035 | 2026-11-17 / 30天内 | v6.22.3 | NOASSERTION | 冻结 Analysis/构建入口；桌面与控制台启动器分别打包 |
| [obsproject/obs-studio](https://github.com/obsproject/obs-studio/blob/717cfa8b7e633853cd21ad2cc656185b3b4255bb/CMakeLists.txt) | 相邻竞品 / C | 79711/11297 | 2026-11-18 / 30天内 | 33.0.1 | GPL-2.0 | 原生模块化构建与发行；参考发布自动化，不引入直播产品范围 |
| [falkTX/Carla](https://github.com/falkTX/Carla/blob/97a9e0740baf6df2df942495c02532a624c44682/Makefile) | 相邻竞品 / C++ | 2204/191 | 2026-03-19 / 180天外 | v2.5.10 | None | 插件宿主构建；许可未明确的快照只作研究，不复制 |
| [DISTRHO/DPF](https://github.com/DISTRHO/DPF/blob/4238e1c7f0351bbe488d79f0899c540543ac7583/Makefile) | 技术参考 / C++ | 885/133 | 2025-10-23 / 180天外 | 无公开 Release/请求未得结果 | ISC | 小型跨平台插件框架；参考边界，暂不扩张插件支持 |
| [muse-sequencer/muse](https://github.com/muse-sequencer/muse/blob/a2b4960deb75765b6055780593f36378f9809728/src/CMakeLists.txt) | 相邻竞品 / C++ | 823/90 | 2026-11-17 / 30天内 | latest | NOASSERTION | src 原生编辑器构建；MIDI 音序不作为核心需求 |
| [wwmm/easyeffects](https://github.com/wwmm/easyeffects/blob/ea72583f1e986e6ea14830bd8169199c85190467/CMakeLists.txt) | 相邻竞品 / HTML | 10519/395 | 2026-11-17 / 30天内 | 无公开 Release/请求未得结果 | GPL-3.0 | Qt/CMake 和 Linux 音频链；源码布局已变化，不能沿用旧 Meson 假设 |
| [bmc0/dsp](https://github.com/bmc0/dsp/blob/2e7eac120f21484f76db478d62eaed02489a6d56/effects_chain.c) | 技术参考 / C | 263/29 | 2026-09-30 / 90天内 | 无公开 Release/请求未得结果 | ISC | effects_chain C 管线；命令行可组合处理启发本轮批处理入口 |

成功读取源码入口 **34** 个；其余请求如实列在证据中，不计入成功项目。

## 证据限制与近期观察

每个仓库的前三个开放 Issue 只用于发现问题线索，不能据此宣称某需求“高频”。Release 日期、名称、最新提交日期和归档状态均来自 API。30/90/180 天窗口表示最后一次提交时间，不能冒充完整活动统计或最近新增功能清单。Zrythm/EasyEffects 当前根目录使用 CMake，旧 Meson 路径请求返回 404 后已重新核查；Demucs 归档状态需作为长期依赖风险。ONNX Runtime 仓库 API 返回 404，故本轮改查官方执行提供程序文档，并以本地 wheel 实际推理为独立证据。模型权重、测试语料与原生库的许可各自独立，不能因 Python 包 MIT 就自动推断权重允许再分发。

## 功能差距和 UI/架构决定

| 维度 | 本项目起点 | 参考实现 | 本轮决定 |
|---|---|---|---|
| 非破坏音频编辑 | 已有帧坐标、引用素材、撤销 | Audacity/Ardour 原生桌面 | 保留并纳入原有回归 |
| 模型多后端 | 已有固定 ONNX、子进程回退 | UVR/Spleeter/audio-separator 调度边界 | 继续共享服务，暂不增加未验收模型 |
| 批处理 | 无公开 CLI | bmc0/dsp 处理链、分离器门面 | 新增同引擎 CLI，结构化结果、失败隔离 |
| 平台分发 | 只有 Windows 本地脚本 | CMake 原生项目和 PyInstaller | 先原生 CI/源码适配，不用套壳或空安装包 |
| 更新 | 自定义版本字符串查询 | 官方 GitHub Releases + 独立密码签名设计 | 新增可验证下载；自动回滚独立延期 |
| UI | 既有工作台、曲线与效果器 | Audacity 分析/编辑边界、Ardour 会话 | 保留视觉语言；更新窗口只显示版本、说明和操作进度 |

关键技术收益是把批处理和平台规则从主窗口中分离，沿用 service 的事务提交语义。没有借入竞品品牌、素材、界面资源或 GPL/商业音频算法。未打开实际竞品 GUI，不能宣称完成其视觉可用性实测。

## 升级候选（优先级、成本与实施）

| 编号 | 具体升级 | 参考依据/价值 | 优先级 | 难度 | 决定 |
|---|---|---|---|---|---|
| 01 | 四 runner 原生 CI | PyInstaller/跨平台桌面构建 | P0 | 中 | 实施 |
| 02 | Ruff 与版本一致性门禁 | 原项目三处版本重复 | P0 | 低 | 实施 |
| 03 | 固定 Action SHA | GitHub 官方工作流安全 | P0 | 低 | 实施 |
| 04 | main 分支保护 | 原仓库无保护 | P0 | 低 | 实施 |
| 05 | 最小工作流权限 | GitHub 官方权限模型 | P0 | 低 | 实施 |
| 06 | Dependabot 周期依赖提案 | 持续维护需求 | P1 | 低 | 实施 |
| 07 | 依赖漏洞扫描与 PR 审查 | 第三方数值/编解码运行库 | P0 | 中 | 实施 |
| 08 | Issue/PR/CODEOWNERS | 可复现设备和更新故障 | P1 | 低 | 实施 |
| 09 | 私密漏洞报告 | 音频文件解析安全 | P0 | 低 | 实施 |
| 10 | 统一版本命令 | PyInstaller/Inno 双入口 | P1 | 低 | 实施 |
| 11 | 版本化资产命名 | 多平台分发可追踪性 | P1 | 低 | 实施 |
| 12 | 标签自动构建发布 | 桌面项目自动化构建 | P0 | 高 | 实施 |
| 13 | Ed25519 更新清单 | 版本字符串不能认证安装器 | P0 | 高 | 实施 |
| 14 | 严格来源与重定向限制 | GitHub 官方资产分发 | P0 | 中 | 实施 |
| 15 | 下载上限/磁盘检查/原子提交 | 模型中心已有安全传输原则 | P0 | 中 | 实施 |
| 16 | 安装前重新哈希 | 下载后缓存被修改 | P0 | 低 | 实施 |
| 17 | 官方更新说明与下载进度 | 成熟桌面更新交互 | P1 | 中 | 实施 |
| 18 | 安装自动回滚/启动健康检查 | 完整更新生命周期 | P1 | 高 | 延期：需事务安装器与真实故障验收 |
| 19 | Authenticode | Windows 系统来源验证 | P1 | 中 | 阻塞：无证书 |
| 20 | macOS 签名/公证 DMG | Qt 原生平台分发 | P1 | 高 | 阻塞：无 Developer ID/实机 |
| 21 | Linux AppImage/DEB/RPM | Ardour/Tenacity 分发 | P2 | 高 | 延期：发行版和编解码许可验收 |
| 22 | XDG/Application Support | 平台原生文件规范 | P1 | 低 | 实施 |
| 23 | 系统字体与默认设备文案 | Qt 桌面交互 | P1 | 低 | 实施 |
| 24 | 条件 ONNX/PE 依赖 | DirectML 仅限 Windows | P0 | 中 | 实施 |
| 25 | CLI 分析 JSON | bmc0/dsp 管线与离线测量 | P1 | 中 | 实施 |
| 26 | 串行批量调音/失败隔离 | audio-separator 批处理思路 | P1 | 中 | 实施 |
| 27 | CLI 防覆盖与碰撞报告 | 现有 audioio 非破坏原则 | P0 | 低 | 实施 |
| 28 | 独立控制台 EXE | PyInstaller GUI 无控制台限制 | P1 | 低 | 实施 |
| 29 | 每月上游证据工件 | 框架/项目近期迁移观察 | P2 | 中 | 实施 |
| 30 | 完整平台/维护仪表盘 | 原文档仅 Windows | P1 | 低 | 实施 |
| 31 | RNNoise 推理集成 | RNNoise 固定帧设计 | P2 | 高 | 延期：立体声与音质听审 |
| 32 | Rubber Band 共振峰保护 | Rubber Band API | P2 | 高 | 延期：授权与音质比较 |
| 33 | VST3 插件隔离 | Carla/VST3 SDK | P3 | 高 | 延期：宿主与沙箱维护成本 |
| 34 | MIDI/谱面导出 | Basic Pitch/MuseScore | P3 | 高 | 不实施：超出核心定位 |
| 35 | Web 上传任务服务 | Voice Changer 服务架构 | P3 | 高 | 不实施：离线隐私与运维范围变化 |
| 36 | 移动触控工作站 | 桌面项目平台差异 | P3 | 高 | 延期：独立 UI/音频会话和设备资源 |

“实施”表示本轮写入实现或配置，实际 PASS/FAIL/BLOCKED 见 [交付记录](DELIVERY-020.md)。每月 Upstream research 工作流保存证据工件，维护者审核差异后再决定任务；重大版本需重新深度核查许可证、源码和真实设备。
