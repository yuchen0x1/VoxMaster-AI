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
