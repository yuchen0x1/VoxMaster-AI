# 0.3.0 上游研究与升级候选

观察时间：2026-11-19（Asia/Shanghai），证据为 GitHub API 实际返回，原始字段保留在 [evidence-030/upstreams.json](evidence-030/upstreams.json)（37 仓基础信息与源码入口抽查）和 [evidence-030/recent.json](evidence-030/recent.json)（90 天窗口提交活动，共 532 条提交；近 30 天活跃 21 仓、近 90 天活跃 23 仓）。本轮新增 `scripts/research_recent.py`，以后每月维护工作流可以重跑同一窗口分析。

本轮继续 0.2.0 的 37 仓清单（[RESEARCH-020](RESEARCH-020.md) 保留完整逐仓表格与许可快照），在此基础上重点回答"最近三个月同行在做什么"。基础信息与 Stars 以下游证据文件为准，不逐行复制。本轮仍不导入任何研究项目代码，不改变整仓授权状态。

## 近 90 天动态与相关性

以下条目均来自 recent.json 中的真实提交主题，标注与本项目的关联：

| 上游动态 | 时间 | 与本项目的关联 | 决定 |
|---|---|---|---|
| [python-audio-separator v0.48.0](https://github.com/nomadkaraoke/python-audio-separator) "download models from our mirror first and verify SHA-256" 及 v0.47.2 "refuse untrusted globals when loading model checkpoints" | 2026-10-29 | 模型分发镜像 + 强校验是同类项目近期的安全重点。本项目模型下载已有逐文件 SHA-256 与固定来源；镜像意味着信任面扩大 | 维持单一官方来源 + 哈希校验；镜像需要签名元数据另行设计，暂不做 |
| [PyAV](https://github.com/PyAV-Org/PyAV) "Release the GIL when opening a codec"（fixes #2517）、"Update ffmpeg binaries" | 2026-11-18 | 打开编解码器释放 GIL 可改善导入大文件时的界面响应。但升级 PyAV 18→19 需要重新验证发布编解码库替换链 | 列为候选，本轮不升级（见差距表） |
| [PortAudio](https://github.com/PortAudio/portaudio) "Fix coreaudio startstop deadlock" | 2026-10-23 | macOS 源码环境的播放稳定性；本项目 CI 使用 brew 的 portaudio，随系统库更新 | 记录为 macOS 源码用户升级指引，无需改代码 |
| [python-sounddevice](https://github.com/spatialaudio/python-sounddevice) "Use the midpoint for unsigned 8-bit playback silence" | 2026-10-18 | 本项目内部总线为 float32，不经过 u8 静音路径 | 不适用 |
| [Audacity](https://github.com/audacity/audacity) 4.0.2 持续重构 DockWindow/资源分层 | 2026-11-18 | 直接竞品仍在重构桌面布局框架；本项目布局稳定，不需要跟进框架级重构 | 观察 |
| [Zrythm](https://github.com/zrythm/zrythm) v2.0.0-alpha.8 "typed store/operations layer" | 2026-11-14 | 会话状态分层的参考；本项目已有 service 事务语义 | 观察 |
| [JUCE](https://github.com/juce-framework/JUCE) 9.0.5 "JSON: Limit the nesting depth" 等解析加固 | 2026-11-02 | 解析器深度/嵌套加固思路适用于自研 JSON 工程读取；本项目工程文件为本地生成、读取有结构检查 | 已由 storage 结构检查覆盖，记录思路 |
| [LMMS](https://github.com/LMMS/lmms) Qt 子窗口生命周期修复 | 2026-11-12 | Qt Widgets 生命周期问题提示本项目对话框父链审查；现有测试覆盖主窗口构建 | 已覆盖 |
| [Tenacity](https://github.com/tenacityteam/tenacity) "AppImage: Let system FFmpeg load" | 2026-11-17 | 佐证"发行物自带专用编解码库 vs 系统库"的取舍；本项目发行物自带专用库并逐项列许可 | 维持现状 |
| 其余 23 仓近 90 天有提交、11 仓无 90 天内提交 | — | RNNoise、rubberband、aubio、basic-pitch、Carla、DPF、vst3sdk、onnxruntime（仓库 404，以官方 wheel 为证据）、pyloudnorm、demucs（已归档）、w-okada 等属慢周期基础设施或归档项目，0.2.0 表格中的快照仍然有效 | 维持 0.2.0 决定 |

`Stazed/loopidity` 在 API 上已不可达（HTTP 404），`muse-sequencer/muse` 与 `wwmm/easyeffects` 的源码入口路径变化导致本轮源码抽查失败——这些是证据限制，不是对项目价值的判断。onnxruntime 仓库 API 在 0.2.0 已返回 404，本轮以本地 wheel 实际推理为证据。

## 功能差距清单（对照近 90 天同类实践）

| 维度 | 本项目现状 | 同类参考 | 差距定级 |
|---|---|---|---|
| 工作流质量门禁 | 无 Actions 配置静态校验；0.2.0 配置曾因上下文违规导致全部工作流启动失败且无日志 | 多数活跃上游在 CI 中运行 workflow lint | A：必须补齐 |
| 更新后健康验证 | 无安装后健康记录；无法区分"更新后异常"与"运行中异常" | 同类项目普遍记录崩溃/会话日志 | A：必须补齐（轻量方案） |
| 批处理自动化报告 | CLI 输出仅打印 stdout | bmc0/dsp、分离器门面均产生结构化产物 | A：必须补齐 |
| 发布后链接验证 | release.yml 无发布后验证步骤 | 提示词要求与同类发布实践一致 | A：必须补齐 |
| 月度上游扫描 | maintenance.yml 只跑基础研究 | 本轮新增 recent 窗口分析 | A：必须补齐 |
| 更新窗口信任透明 | 校验结果只有文字"已校验"，未展示大小/摘要 | audio-separator 强调可见校验 | B：提升竞争力 |
| 编解码器 GIL | PyAV 18.1.0 打开文件时持有 GIL | PyAV 19 已修复 | C：需整链回归，暂缓 |
| 模型镜像 | 单一来源 + SHA-256 | audio-separator 镜像优先 | D：信任面扩大，收益有限 |
| 自动回滚 | 无（交互式安装器） | 大型 DAW 无成熟轻量方案 | D：需安装器级投入 |
| Authenticode / 公证 | 未签名 | 商业产品标配 | D：无证书阻塞 |
| Linux 原生安装包 | 源码 + CI 试验 | Tenacity/ EasyEffects 有 AppImage/Flatpak | C：无实机验收不做 |
| 实时变声/声线转换 | 不做 | RVC、w-okada | D：超出离线调音定位 |

## 升级候选清单（本轮 33 项）

| 编号 | 升级内容 | 参考依据 | 优先级 | 难度 | 决定 |
|---|---|---|---|---|---|
| 01 | 修复 ci/release 工作流 `runner` 上下文违规导致的启动失败 | actionlint 检出；全部工作流 0 作业失败 | 高 | 低 | 本轮实施（已完成） |
| 02 | CI 增加 actionlint 工作流静态校验 | 上游 CI 实践；防止配置回归 | 高 | 低 | 本轮实施 |
| 03 | 启动健康检查：会话标记、异常退出识别 | 同类会话日志实践；0.2.0 遗留缺口 | 高 | 中 | 本轮实施 |
| 04 | 启动时提示上次异常退出 | 03 的用户可见面 | 中 | 低 | 本轮实施 |
| 05 | CLI `--report` 输出结构化报告文件 | bmc0/dsp 结构化产物 | 高 | 低 | 本轮实施 |
| 06 | CLI `styles` 子命令输出风格清单 JSON | 自动化调用友好 | 中 | 低 | 本轮实施 |
| 07 | release.yml 发布后重读官方清单并逐资产验证 | 提示词"验证下载链接/更新接口" | 高 | 低 | 本轮实施 |
| 08 | maintenance.yml 增加近 90 天上游活动扫描 | 提示词"持续更新分析" | 中 | 低 | 本轮实施 |
| 09 | 更新窗口展示包体大小与 SHA-256 前缀 | audio-separator 可见校验 | 中 | 低 | 本轮实施 |
| 10 | 新增 `research_recent.py` 窗口分析脚本 | 提示词"持续更新分析" | 中 | 低 | 本轮实施 |
| 11 | RESEARCH-030 / DELIVERY-030 文档 | 提示词交付要求 | 中 | 低 | 本轮实施 |
| 12 | README/CHANGELOG/release-notes 0.3.0 更新 | 版本发布要求 | 中 | 低 | 本轮实施 |
| 13 | 版本号统一 0.3.0（version.py --set） | 统一版本管理 | 中 | 低 | 本轮实施 |
| 14 | 全量回归 + 新增用例 | 质量基线 | 高 | 中 | 本轮实施 |
| 15 | PyAV 18→19 升级获得 GIL 释放 | PyAV #2517 修复 | 中 | 高 | 评估：发布编解码替换链需整链重验，暂缓 |
| 16 | 设备热插拔恢复 | PortAudio 上游修复提示 | 中 | 高 | 已覆盖：playback 已有 poll_device/默认设备回退；实体拔插仍待实机验收 |
| 17 | 模型镜像下载 | audio-separator v0.48.0 | 低 | 中 | 暂缓：需签名元数据，信任面扩大 |
| 18 | 模型加载"拒绝不可信全局"加固 | audio-separator v0.47.2 | 低 | 中 | 已覆盖：权重先 SHA-256 后加载 |
| 19 | 更新自动回滚 | 大型桌面软件实践 | 低 | 高 | 暂缓：需安装器集成 |
| 20 | 启动健康检查扩展为崩溃上报 | 同类崩溃收集 | 低 | 中 | 暂缓：离线产品不做遥测 |
| 21 | Windows 10 实机验收 | 0.2.0 遗留 | 高 | 低 | 阻塞：无 Win10 实机 |
| 22 | Authenticode 签名 | 提示词要求 | 高 | 低 | 阻塞：无证书 |
| 23 | macOS 签名公证 | 提示词要求 | 中 | 高 | 阻塞：无 Apple 开发者账号 |
| 24 | Linux DEB/RPM/AppImage | Tenacity 等 | 中 | 高 | 暂缓：无实机验收，不发布未验证安装包 |
| 25 | u8 静音中点修正 | sounddevice #645 | 低 | 低 | 不适用：内部总线 float32 |
| 26 | JSON 工程读取深度加固 | JUCE 9.0.5 思路 | 低 | 中 | 已覆盖：storage 结构检查 + 版本备份 |
| 27 | Qt 对话框生命周期审查 | LMMS 修复提示 | 低 | 中 | 已由现有窗口测试覆盖 |
| 28 | 发布编解码库跟随 PyAV 更新 | PyAV "Update ffmpeg binaries" | 中 | 高 | 暂缓：与 15 同链路，需专项验证 |
| 29 | 界面英文翻译 | 多数上游双语 | 低 | 高 | 暂缓：当前用户群中文，收益低 |
| 30 | VST3 插件宿主 | vst3sdk | 低 | 高 | 暂缓：超出离线调音定位 |
| 31 | 实时变声 | RVC/w-okada | 低 | 高 | 暂缓：定位与授权成本 |
| 32 | RNNoise 神经降噪 | xiph/rnnoise | 低 | 中 | 暂缓：现有立体声算法可用，新增运行库成本高 |
| 33 | rubberband/aubio 伸缩与音高算法 | 上游项目 | 低 | 中 | 暂缓：GPL 许可与整仓授权状态冲突 |

实施项共 14 项（01–14）；其余按价值与阻塞原因分别标注评估、已覆盖、阻塞或暂缓。本轮不含任何未验证声明：Linux/macOS 仍为源码与 CI 试验支持，Windows 实机验收缺口保持记录。
