# 0.5.1 开源参考与取舍

核验时间：2026-11-21（本机 UTC+08:00）。通过 GitHub 官方仓库 API 读取实际 README、许可证及下面列出的实现文件；网页抓取出现超时/连接重置后改用 GitHub API。未运行第三方应用，未下载权重，不据此声称竞品性能或分离音质排名。`pushed_at` 仅表示仓库更新，不等于稳定版本发布日期。

## 六个参考仓库

| 项目及一手来源 | 许可核验与最近仓库更新（UTC） | 实际观察与当前项目差异 | 本轮取舍 |
|---|---|---|---|
| [Audacity](https://github.com/audacity/audacity) · [README](https://github.com/audacity/audacity/blob/master/README.md) · [LICENSE](https://github.com/audacity/audacity/blob/master/LICENSE.txt) | README 明确发行版 GPLv3、多数源文件 GPLv2-or-later、文档 CC BY 3.0；API 自动识别为 NOASSERTION，未将它误记为 MIT。更新 2026-11-20 | 跨平台多轨编辑/录音；主分支正在向 Audacity 4 的新界面和结构迁移，3.x 有独立维护入口。VoxMaster 面向本地人声/歌曲的测量、调音与制作，不应照搬完整通用 DAW。 | 借鉴保留成熟能力、将迭代限制在明确工作流的做法；不复制 GPL 实现，不更换本项目双主题或界面框架。 |
| [Ardour](https://github.com/Ardour/ardour) · [COPYING](https://github.com/Ardour/ardour/blob/master/COPYING) · [session_state.cc](https://github.com/Ardour/ardour/blob/master/libs/ardour/session_state.cc) | COPYING 明确 GPL v2.0 or later；API 自动识别 NOASSERTION。更新 2026-11-19 | 实际源文件区分会话路径、备份、快照、待恢复状态，具有比当前 `.voxproj` 更广的 DAW 会话管理。主 README 将构建和用户文档导向官方网站。 | 采用“可恢复的会话状态与当前路径应一致”的设计原则，修复本项目 `.history` 引用搬迁；不引入其 C++ 会话格式或插件体系。 |
| [Ultimate Vocal Remover GUI](https://github.com/Anjok07/ultimatevocalremovergui) · [README](https://github.com/Anjok07/ultimatevocalremovergui/blob/master/README.md#license) | README 声明 MIT，API 元数据 MIT；当前根目录缺少该 README 链接的 LICENSE，license API 返回 404，因此未取得独立许可文件、未导入其代码。更新 2026-10-06 | 专注模型分离，提供含 Python/推理库的桌面包，并分别说明 DirectML、Mac MPS、外部编解码及变调工具的适用范围。它的模型覆盖广于本项目固定 Spleeter 双轨。 | 吸收“按设备明确展示适用边界、单独说明模型与第三方依赖”的原则。未照搬关闭系统安全检查的安装建议，未自动增加大模型或 PyTorch。 |
| [python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator) · [README](https://github.com/nomadkaraoke/python-audio-separator/blob/main/README.md) · [LICENSE](https://github.com/nomadkaraoke/python-audio-separator/blob/main/LICENSE) | MIT。更新 2026-10-29 | CLI/Python API、批量、多模型及多类分轨；README 区分 CPU、CUDA、Apple MPS/CoreML、DirectML，以及长文件工作缓冲预算。DirectML 一处概述仍写实验/未在 CI 测试，后面的架构表又写专门 CI 验证，未把这类文档差异当成本项目的实测证据。 | 保留本项目共享服务层和明确设备回退；把多模型插件/长音频流式化列后续，而不是增加未验收依赖、照抄性能数字。 |
| [Spleeter](https://github.com/deezer/spleeter) · [README](https://github.com/deezer/spleeter/blob/master/README.md) · [模型 provider](https://github.com/deezer/spleeter/blob/master/spleeter/model/provider/__init__.py) · [LICENSE](https://github.com/deezer/spleeter/blob/master/LICENSE) | 源码 MIT；模型、素材授权仍须分别核实。更新 2026-10-28 | TensorFlow 实现，支持 2/4/5 stems、CLI/Python/Docker。provider 通过模型目录与 probe 文件管理获取；本项目是现有固定 ONNX 转换和 SHA-256 校验，并非直接嵌入完整 TensorFlow 应用。 | 坚持固定版本/哈希与离线可用，不将目录存在当作可用模型证明；修复本项目并发迁移的过期源目录检查。不新增模型、不改变现有分离算法。 |
| [pyloudnorm](https://github.com/csteinmetz1/pyloudnorm) · [README](https://github.com/csteinmetz1/pyloudnorm/blob/master/README.md) · [meter.py](https://github.com/csteinmetz1/pyloudnorm/blob/master/pyloudnorm/meter.py) · [LICENSE](https://github.com/csteinmetz1/pyloudnorm/blob/master/LICENSE) | MIT。更新 2026-01-04 | NumPy/SciPy 响度计；实际 meter 实现提供块长、K 加权、绝对/相对门限；README 还说明 LRA 及不同滤波器。VoxMaster 已有单/双声道响度、四倍真峰值与质量报告。 | 后续可用独立离线基准扩大计量交叉验证；本轮不更换既有响度/DSP，不把界面与事务修复宣传为音质或 LUFS 精度提升。 |

## 按维度比较与落地

| 维度 | 当前项目的实际基础 | 参考启发 | 本轮实际升级/边界 |
|---|---|---|---|
| 功能完整度 | 独立人声、整曲分离/混音、多轨、参考匹配、CLI | UVR、audio-separator 的设备/模型范围透明 | 优先修复已有工作流的数据一致性；不堆砌分离模型或插件功能。 |
| UI/UX | 原生 Qt Widgets、系统/浅/深主题、时间轴键盘操作 | Audacity 的分阶段界面演进、UVR 的状态提示 | 更新取消会等待后台线程收尾并关闭窗口；工程保存成功与最近记录写入失败分开反馈。 |
| 性能 | 大文件解码可用 memmap、后台任务、已解码 PCM 复用；全渲染仍需整轨缓冲 | audio-separator 明确区分推理设备与工作缓冲预算 | 不改变 DSP；增加外部素材哈希 I/O，保留内容不变时的 PCM 复用。未宣称更快或更省内存。 |
| 架构/数据 | `.voxproj` v1 JSON、非破坏性片段、原子文件写入、恢复点 | Ardour 的路径/快照分工 | 将外部素材纳入既有媒体身份/提交前校验；备份按实际存放目录重算相对引用，保持 v1 可读。 |
| 安全 | Ed25519 更新清单、包长度/哈希、固定 ONNX、无素材上传 | Spleeter provider 的目录职责及本项目已有校验边界 | 锁后复核迁移源，取消后不继续元数据工作或发布下载文件；不放松签名、听审、安装验收门禁。 |
| 扩展性/自动化 | 共用 service/CLI、四系统 CI、候选与公开发布分离 | audio-separator 的 CLI/API；pyloudnorm 的独立计量接口 | 扩充确定性竞态与故障注入测试；多模型、长轨流式化和独立计量基准另列路线。 |

## 许可和整合结论

本轮没有复制上述项目的源代码、界面资产或模型，也没有新增运行依赖。GPL 项目仅用于理解设计原则；MIT 项目亦不自动授权其所有模型、音频或间接依赖。UVR 独立 LICENSE 文件缺失的核验边界已保留，不以 README 声明代替代码整合所需的完整许可核对。当前项目原有第三方声明继续适用，见 [THIRD_PARTY](THIRD_PARTY.md)。

## 最终整合轮的六仓库精确快照复核

2026-11-21 通过官方公共 API、README、许可正文与相关源码重新查证以下六个仓库。此表是单独的只读研究快照，不把上表的分支链接当作不可变证据；没有克隆运行竞品、下载权重、复制实现或进行速度、内存、音质、取消延迟及安装横向实测。上游 API 的自动许可识别与正文不同时，以实际正文及具体组件为准。

| 仓库、默认分支、核对提交 | 许可与维护边界 | 实际源码观察 | 对当前整合的启发与限制 |
|---|---|---|---|
| Audacity · master · `97db61c263888efddffe54ffd1621d179afde770` · [工程 I/O](https://github.com/audacity/audacity/blob/97db61c263888efddffe54ffd1621d179afde770/au3/libraries/au3-project-file-io/ProjectFileIO.cpp) · [许可](https://github.com/audacity/audacity/blob/97db61c263888efddffe54ffd1621d179afde770/LICENSE.txt) | 未归档；发行版 GPLv3，多数源码 GPLv2-or-later，文档 CC BY 3.0 | SQLite 工程中区分 project、autosave、project_history，临时文件、安全备份和事务有不同职责；取消由原子标志通知可取消对象 | 借恢复入口在附属设置损坏时仍应可用的原则，不引入 SQLite/通用 DAW，也不复制 GPL 代码；所读文件不足以评价整个项目的外部媒体哈希策略 |
| Ardour · master · `221970a27b8ed24c24a145b40d118738a8ce17df` · [会话状态](https://github.com/ardour/ardour/blob/221970a27b8ed24c24a145b40d118738a8ce17df/libs/ardour/session_state.cc) · [许可](https://github.com/ardour/ardour/blob/221970a27b8ed24c24a145b40d118738a8ce17df/COPYING) | 未归档；GPLv2-or-later | 明确区分会话目录、interchange 素材、外部引用、快照、备份、自动保存和待恢复状态；进度窗口单列取消 | 本项目继续使用兼容 v1 的 JSON/相对素材引用，逐条隔离恢复候选失败而不自动覆盖当前工程；不搬入 C++ 会话或插件框架 |
| Mixxx · main · `825e45199b1c68e42035eea30cd796eb7577a841` · [扫描任务](https://github.com/mixxxdj/mixxx/blob/825e45199b1c68e42035eea30cd796eb7577a841/src/library/scanner/recursivescandirectorytask.cpp) · [许可](https://github.com/mixxxdj/mixxx/blob/825e45199b1c68e42035eea30cd796eb7577a841/LICENSE) | 未归档；GPLv2，另有 LGPL/其他组件声明 | 音乐库保存位置、大小、删除和待验证状态；目录扫描有 SHA-256 文件列表摘要与取消，分析线程使用单生产者/单消费者队列，进度约 60 ms 节流 | 可借批量任务状态/节流，不能把目录列表摘要等同每个音频内容的提交前哈希，也不将 DJ 曲库等同非破坏多轨工程；不复制 GPL 实现 |
| UVR GUI · master · `a5f88453bfb2b38b05a965bcf67727243e0cbf19` · [界面实现](https://github.com/Anjok07/ultimatevocalremovergui/blob/a5f88453bfb2b38b05a965bcf67727243e0cbf19/UVR.py) · [README](https://github.com/Anjok07/ultimatevocalremovergui/blob/a5f88453bfb2b38b05a965bcf67727243e0cbf19/README.md) | 未归档；README/API 声明 MIT，但精确提交根目录无独立 LICENSE，许可接口 404 | Tkinter、多模型/批量/日志与自包含 Python/PyTorch 包；所读实现使用 pickle 设置和 KThread terminate 路径 | 借明确模型/设备及错误状态呈现，不采用不可信 pickle 或强杀线程，不据 MIT 声明导入代码、模型或捆绑工具 |
| Spleeter · master · `6f2c8a2e283914faa544631430f65b793f1b1218` · [分离入口](https://github.com/deezer/spleeter/blob/6f2c8a2e283914faa544631430f65b793f1b1218/spleeter/separator.py) · [许可](https://github.com/deezer/spleeter/blob/6f2c8a2e283914faa544631430f65b793f1b1218/LICENSE) | 未归档；源码 MIT，模型/转换产物另核 | TensorFlow 2/4/5 stems、CLI/API/Docker；模型 provider 以目录和 probe 管理可用性，GitHub provider 临时下载、校验后解包 | 继续固定 ONNX 双轨、SHA 和独立进程，不重新引入 TensorFlow、不因目录存在就认为模型可用；不下载新权重 |
| Demucs · main · `e976d93ecc3865e5757426930257e200846a520a` · [分段推理](https://github.com/facebookresearch/demucs/blob/e976d93ecc3865e5757426930257e200846a520a/demucs/apply.py) · [许可](https://github.com/facebookresearch/demucs/blob/e976d93ecc3865e5757426930257e200846a520a/LICENSE) | **已归档**；源码 MIT，不是持续维护保证 | PyTorch CLI 多输入、CPU/CUDA、two-stems、segment/overlap/shifts、线程池及 cancel_futures；模型仓库有校验和 | 只将重叠分块和细粒度进度列后续；取消待运行 futures 不等同正在运行推理可取消，不把 README 的 SDR/显存数字当本机验收 |

### 安装、安全与扩展取舍

Audacity/Ardour/Mixxx 是更广的原生多轨或 DJ 应用，UVR 以捆绑推理库的桌面分离为中心，Spleeter/Demucs 则主要是库和 CLI；没有证据据此宣称本项目的完整功能或性能超越它们。本轮适合当前产品的实际成果是恢复候选可达、提交收据准确、发行文档与研发证据分层，以及原有包络格式下叠加淡变的正确性。新依赖、新模型、插件主机和全链路流式化暂不引入。下一轮优先测长音频资源与取消时限，再决定分块；模型许可、权重、演示素材及第三方依赖必须分别审阅。
