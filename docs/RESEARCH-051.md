# 0.5.1 开源方案对比与工程取舍

核验时间：2026-11-21。通过 GitHub 官方 API 读取仓库元数据、默认分支准确提交、许可证、README 和下列源码；没有克隆、执行这些仓库、下载模型或做竞品性能测试。提交日期均为默认分支 `commit.committer.date`（UTC），不使用 `updated_at` 冒充代码维护活动。

## 当前项目基线

VoxMaster AI 是 MIT 许可的本地优先人声/歌曲制作工作站。Python 3.11、Qt Widgets/PySide6 负责界面，NumPy/SciPy 执行 DSP，PyAV 负责编解码，PortAudio 监听，固定 SHA-256 的 ONNX Spleeter 模型在隔离子进程中推理。没有 Web 服务、数据库或账号系统。

已具备三模式路由、18 种可编辑风格、参考匹配、音高与尾音编辑、双轨分离、歌曲混音母带、多轨剪辑和自动化、等响 A/B、v1 JSON 工程、恢复副本/历史、CLI、双主题、模型中心、Ed25519 更新和 Windows 安装/便携包。原音、参考及分轨已有内容身份校验；0.5.1 将相同契约扩展至外部时间线素材。

## 六仓库来源与维护、许可快照

| 仓库 | 精确提交与最近提交 UTC | 维护状态与许可观察 |
|---|---|---|
| [Audacity](https://github.com/audacity/audacity) | `97db61c263888efddffe54ffd1621d179afde770` · 2026-11-20 10:44:40 | 未归档；[许可正文](https://github.com/audacity/audacity/blob/97db61c263888efddffe54ffd1621d179afde770/LICENSE.txt) 说明整体 GPLv3、多数文件 GPLv2-or-later，另有例外。当前主分支处于 4.x Qt/QML 重构，不能沿用“纯 wxWidgets”印象。 |
| [Mixxx](https://github.com/mixxxdj/mixxx) | `825e45199b1c68e42035eea30cd796eb7577a841` · 2026-11-20 21:23:29 | 未归档；[GPL-2.0-or-later](https://github.com/mixxxdj/mixxx/blob/825e45199b1c68e42035eea30cd796eb7577a841/LICENSE)，皮肤与第三方文件另查。 |
| [Ardour](https://github.com/Ardour/ardour) | `221970a27b8ed24c24a145b40d118738a8ce17df` · 2026-11-20 20:51:28 | 未归档；[GPL-2.0-or-later](https://github.com/Ardour/ardour/blob/221970a27b8ed24c24a145b40d118738a8ce17df/COPYING)；GitHub 是源码镜像，不把自动源码归档当完整官方安装发行物。 |
| [Ultimate Vocal Remover GUI](https://github.com/Anjok07/ultimatevocalremovergui) | `a5f88453bfb2b38b05a965bcf67727243e0cbf19` · 2026-10-06 22:39:25 | 未归档；API 与 README 声明 MIT，但该固定提交根目录未找到许可正文，license API 返回 404。复制前必须补齐版权/许可链，本轮不复制。 |
| [Demucs](https://github.com/facebookresearch/demucs) | `e976d93ecc3865e5757426930257e200846a520a` · 2023-11-16 12:32:35 | **已归档**，官方 README 说明原仓不再维护；[MIT](https://github.com/facebookresearch/demucs/blob/e976d93ecc3865e5757426930257e200846a520a/LICENSE)。只作算法与内存设计参考。 |
| [Spleeter](https://github.com/deezer/spleeter) | `6f2c8a2e283914faa544631430f65b793f1b1218` · 2026-10-28 15:05:21 | 未归档；[MIT](https://github.com/deezer/spleeter/blob/6f2c8a2e283914faa544631430f65b793f1b1218/LICENSE)。官方实现为 TensorFlow，不是本项目使用的 ONNX 转换运行库。 |

UVR、Spleeter 最新提交只改 README；路径抽样中 UVR.py 最近修改为 2023-10-18，Spleeter separator.py 最近修改为 2025-01-24 的格式化。不能据“未归档/刚更新”断言所有核心路径持续活跃。

## 具体实现观察

### Audacity：恢复与撤销

- [工程保存与备份](https://github.com/audacity/audacity/blob/97db61c263888efddffe54ffd1621d179afde770/au3/libraries/au3-project-file-io/ProjectFileIO.cpp#L1423-L1603) 处理 SQLite 主文件及 WAL/SHM；失败有备份恢复逻辑，不能只复制主数据库就宣称事务安全。
- [UndoManager](https://github.com/audacity/audacity/blob/97db61c263888efddffe54ffd1621d179afde770/au3/libraries/au3-project-history/UndoManager.cpp#L237-L272) 区分合并同类动作、清理 redo 与历史生命周期。
- [当前新导出层](https://github.com/audacity/audacity/blob/97db61c263888efddffe54ffd1621d179afde770/src/importexport/export/internal/au3/au3exporter.cpp#L252-L307) 有后台/取消标志，但所查函数的 actualFilename 与 targetFilename 初值相同。不能看到 rename 字样就推定全调用链已具备原子覆盖。
- 取舍：学习工程/资产/历史分层；不搬 GPL 代码，不追随重构中的整套 UI 架构。

### Mixxx：有限缓存、预读、进度节流

- [CachingReader](https://github.com/mixxxdj/mixxx/blob/825e45199b1c68e42035eea30cd796eb7577a841/src/engine/cachingreader/cachingreader.h#L62-L78) 把解码放到工作线程，按播放头/cue/loop 提示预读；[实现](https://github.com/mixxxdj/mixxx/blob/825e45199b1c68e42035eea30cd796eb7577a841/src/engine/cachingreader/cachingreader.cpp#L15-L78) 使用有限音频块和 LRU，而非无限缓存。实时回调不应做磁盘 I/O。
- [分析线程](https://github.com/mixxxdj/mixxx/blob/825e45199b1c68e42035eea30cd796eb7577a841/src/analyzer/analyzerthread.cpp#L29-L35) 有约 60ms 的进度更新节流；[数据库事务](https://github.com/mixxxdj/mixxx/blob/825e45199b1c68e42035eea30cd796eb7577a841/src/util/db/sqltransaction.cpp#L50-L79) 可回滚未提交操作。
- [曲库导出覆盖](https://github.com/mixxxdj/mixxx/blob/825e45199b1c68e42035eea30cd796eb7577a841/src/library/export/trackexportworker.cpp) 先删除目标再复制。此观察仅限曲库复制路径，不是对全部录音编码器下结论；本项目不借鉴这种覆盖顺序。
- 取舍：有限缓存与预读列后续路线；本轮不重写已工作的离线渲染链。

### Ardour：复合命令与会话提交

- [会话保存](https://github.com/Ardour/ardour/blob/221970a27b8ed24c24a145b40d118738a8ce17df/libs/ardour/session_state.cc) 备份旧状态，写临时文件，检查重命名失败；这不是“已证明所有断电场景安全”。
- [UndoTransaction](https://github.com/Ardour/ardour/blob/221970a27b8ed24c24a145b40d118738a8ce17df/libs/pbd/undo.cc#L121-L141) 正序执行、逆序撤销；[Butler](https://github.com/Ardour/ardour/blob/221970a27b8ed24c24a145b40d118738a8ce17df/libs/ardour/butler.cc#L58-L98) 管理后台磁盘服务与缓冲。
- [导出界面](https://github.com/Ardour/ardour/blob/221970a27b8ed24c24a145b40d118738a8ce17df/gtk2_ardour/export_dialog.cc#L147-L165) 明示覆盖、分析、导出和取消。
- 取舍：一个用户动作一次事务；只学思想，不迁移 GTK 或 GPL 引擎。

### UVR：分离工作台流程

- [Python Tk/ttk UI](https://github.com/Anjok07/ultimatevocalremovergui/blob/a5f88453bfb2b38b05a965bcf67727243e0cbf19/UVR.py#L5440-L5485)、[ONNX 分块路径](https://github.com/Anjok07/ultimatevocalremovergui/blob/a5f88453bfb2b38b05a965bcf67727243e0cbf19/separate.py#L477-L600) 展示多模型/参数/批量输出流程；不能当作 Qt Widgets 骨架。
- 设置用 [pickle](https://github.com/Anjok07/ultimatevocalremovergui/blob/a5f88453bfb2b38b05a965bcf67727243e0cbf19/UVR.py#L160-L181)，[停止](https://github.com/Anjok07/ultimatevocalremovergui/blob/a5f88453bfb2b38b05a965bcf67727243e0cbf19/UVR.py#L6247-L6269) 使用线程 terminate，输出直接 sf.write。它们不适合作为本项目不可信工程解析或协作取消/事务导出的替代。
- 取舍：借鉴模型信息分组和可解释流程；不引入巨大后端集合，许可链未补齐前不复制代码。

### Demucs：分块不等于全链路恒定内存

- [apply_model](https://github.com/facebookresearch/demucs/blob/e976d93ecc3865e5757426930257e200846a520a/demucs/apply.py#L257-L322) 有重叠/权重融合、回调和 no_grad，但仍为整段 stem 分配输出，并建立分块任务列表。缩小 segment 不能证明长音频总 RAM 恒定。
- [模型仓库](https://github.com/facebookresearch/demucs/blob/e976d93ecc3865e5757426930257e200846a520a/demucs/repo.py#L29-L107) 对远程模型检查 hash；本地模型是否检查取决于元数据。逐 stem [rescale](https://github.com/facebookresearch/demucs/blob/e976d93ecc3865e5757426930257e200846a520a/demucs/audio.py#L218-L265) 可能改变相对增益。
- 取舍：重叠融合/预算思路可参考，不为数量引入 PyTorch 依赖，更不自动下载新权重。

### Spleeter：协议分层而非直接替换后端

- Separator/AudioAdapter/ModelProvider 分离职责；[依赖](https://github.com/deezer/spleeter/blob/6f2c8a2e283914faa544631430f65b793f1b1218/pyproject.toml#L47-L58) 要求 Python <3.12、TensorFlow 2.12.1、NumPy <2，不能整包替换本项目 NumPy 2 + ONNX 运行栈。
- [模型下载](https://github.com/deezer/spleeter/blob/6f2c8a2e283914faa544631430f65b793f1b1218/spleeter/model/provider/github.py#L131-L162) 校验 SHA-256，但 tar.extractall 没有在所查调用中显式过滤路径；[完成标记](https://github.com/deezer/spleeter/blob/6f2c8a2e283914faa544631430f65b793f1b1218/spleeter/model/provider/__init__.py#L75-L85) 的已有未完成目录处理亦不能照搬。
- [保存队列](https://github.com/deezer/spleeter/blob/6f2c8a2e283914faa544631430f65b793f1b1218/spleeter/separator.py#L127-L138) 先无超时 task.get 再处理 join，不构成完整的有界取消协议。
- 取舍：保持现有固定版本/哈希/锁/离线推理边界，转换模型的协议与权重许可单独核验。

## 六维对比及本轮落点

| 维度 | VoxMaster 基线 | 参考观察 | 可执行升级/取舍 |
|---|---|---|---|
| 功能完整度 | 人声、整曲、多轨已闭环；缺失素材取消后须重开 | Ardour/Audacity 区分恢复状态与工程状态 | 0.5.1 增加窗口内重试，不允许应用占位会话 |
| UI/UX | 已有双主题、键盘控制；导出终态有竞态 | UVR 产品分组可参考，但强停线程不合适 | 明示已导出/清理警告；失败候选可改选；不再重做主题 |
| 性能 | 完整音轨缓冲；缓存按身份复用 | Mixxx 有限块/预读；Demucs 仍分配全长输出 | 保留未变素材缓存；补内容校验有额外线性 I/O，不宣称提速；流式化另立预算 |
| 架构 | service 事务重建与独立混音器 | Ardour 复合事务/后台磁盘层 | 外部源复用同一 hash/commit 合约，不造第二套完整性框架 |
| 安全/数据 | 禁止覆盖音频、签名更新、固定模型；外部源漏终检 | 参考项目各自导出/安装路径并非都安全 | 外部媒体变更/删除拒绝提交；提交后的取消不否认成品；保留安装签名和听审门禁 |
| 扩展性 | v1 工程、CLI、固定 ONNX，未有插件系统 | 三种 DAW/分离架构各有额外复杂度 | 保持格式/依赖兼容；不引入 VST、TensorFlow 或 PyTorch 来凑功能 |

## 许可与证据边界

本轮实现为本项目既有代码上的独立修复，**未复制、逐行翻译 GPL 或其他上游实现，未增加运行依赖或模型**。MIT 代码未来复用仍需保留许可与版权；第三方权重、Qt、编解码器和测试录音的许可不因本项目 MIT 而改变。UVR 的 MIT 声明与许可正文缺口分别记录，不把元数据当完整授权链。

未对六个项目执行安装、音质盲测、基准或完整网络审计；以上是限定路径的可复核源码观察，不是项目优劣评分或全部安全结论。

## 既有可靠性候选的研究记录

以下保留另一候选在同日取得的来源与取舍，不表示本次接续再次运行了竞品或重新研究。

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
