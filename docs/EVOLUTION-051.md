# 0.5.1 工程可靠性升级与验收

核验日期：2026-11-21（本地 UTC+08）。本文是候选升级记录，不代表 v0.5.1 已正式发布。最近正式版本与本轮远程状态须以 GitHub 的实际结果为准，不能把版本号、Tag 或 CI 候选当作正式发行。

本文保留前期分阶段证据。之后的最终整合又复现并修复了根内 Windows junction 归档别名、恢复入口异常设置等问题，并整合导出收据、离线手册与叠加淡变补丁；不能用下表较早快照的通过结果代替这些修改的验收。最终 603 通过、3 跳过以及较深 QA 路径仍失败/物理短目录成功的准确边界见 [最终交付](DELIVERY-051.md)。

## 1. 项目定位与现有能力

VoxMaster AI 是本地优先的人声制作、喊麦调音与歌曲混音桌面工作站；目标用户是需要可编辑处理链、参考试听及本地工程恢复的创作者。它使用 PySide6 Qt Widgets，不是 Web 服务，没有业务数据库或云端音频处理。

| 层次 | 实际实现与已有能力 | 边界 |
| --- | --- | --- |
| 桌面入口 | `app.py`、`vox/interface.py`：独立人声、完整歌曲、多轨三种模式；深浅主题、A/B 等响试听、参数编辑、工程撤销/重做 | 原生 Qt；系统文件选择器和标题栏由 OS 管理 |
| 分析与 DSP | `analysis`、`acoustics`、`engine`：LUFS、4× 真峰值、频带/动态/声道相关，18 种风格、EQ、压缩、齿音、音高和空间处理 | 测量驱动 DSP，不是语义理解或端到端生成式调音 |
| 分离与多轨 | `models_runtime`、`service`、`song`、`studio_session`：固定 Spleeter ONNX 双轨、隔离推理进程、非破坏性剪辑、轨道/总线效果、混音与母带 | 相加重建误差不证明分离听感；不自动下载新模型 |
| 音频 I/O | `audioio`：PyAV、44.1 kHz 双声道 float32 内部总线，WAV/FLAC/MP3/AAC 导出；PortAudio 监听 | 解码可 spool/memmap，完整渲染仍有整轨缓冲，不是全链路流式化 |
| 持久化 | `storage`：JSON `.voxproj` v1、原子保存、历史备份、恢复检查点、本地设置 | 工程引用外部素材，不内嵌全部音频；不是关系数据库 |
| 自动化与发行 | CLI analyze/tune/song/styles；四平台源码 CI、安全检查；PyInstaller/Inno Setup；Ed25519 更新清单、大小和 SHA-256 | 源码 CI 不代表实体声卡/Win10 实机验收；更新签名不是 Authenticode |

实际阅读涉及上述核心实现、依赖、测试、版本脚本、归档、编解码器暂存与发行工作流。不是逐行形式化验证或“全项目零缺陷”保证。[六仓库对比和许可核验](RESEARCH-051.md)单列研究证据及取舍。

## 2. 已复现的问题与修复

| 问题 | 原因与本轮改法 | 回归证据 |
| --- | --- | --- |
| 外部多轨素材被替换后仍使用旧声音 | 原缓存只比较路径/大小/mtime；有效外部引用现在同时比较 SHA-256，并在处理结束提交前复核 | 同大小/mtime 替换、热/冷结果逐采样一致、渲染中替换拒绝提交、不变 PCM 复用 |
| 外部别名遮蔽新解码的内置轨 | 在 stat/哈希前排除 Vocal/已有 stems 的外部同名别名，遵守 `load_sources` 原有优先级 | Vocal/Instrumental 两参数、被遮蔽文件不可读也不强制打开 |
| 历史备份随工程搬迁后丢失素材 | 备份按真实存放目录重新计算相对引用；目录 junction/symlink 用 resolve 后的位置；跨盘回退绝对路径 | source/reference/stems/外部轨整体搬迁、旧绝对路径兼容、junction 与跨盘 |
| 并发模型迁移切换至空目录 | 源/目标锁都取得后复核活动目录；默认 install/remove 取得锁后同样复核 | 确定性交错迁移、过期安装/删除、显式 root 兼容、复制/校验/设置/取消故障 |
| 工程已成功提交却显示任务失败 | 最近工程列表属于附属设置：写入失败显示明确非致命警告；异常 recent 数据先规范化 | 打开/保存/另存、异常 recent、真正工程/恢复点失败仍保留旧事务 |
| 取消更新后继续请求或写入缓存 | 每个 GET 前后、重定向下一跳前、元数据结束与下载最终替换前检查取消 | 无请求取消、302 后不发第二跳、最后块取消保留旧缓存/清理 part |
| 关闭更新窗口时工作线程未结束 | 先发取消，保留窗口直到 finished，再释放 Worker 和关闭；忽略晚到成功/进度 | 真实 Qt Worker 的 reject/close 两路径与正常更新路径 |
| 自定义更新检查关闭后仍回写 UI | 集成并行会话的取消、请求令牌、重复启动保护和关闭清理，保持 `check_version(url)` 兼容 | 14 个生命周期回归，以及独立交叉复核 |
| 源码黑名单遗漏未预见扩展名/越界链接 | 集成正向文件白名单、目录边界及公共夹具/上游来源固定哈希；清单在 LF 规范化后验证内容 | 每个 scope 的哨兵、越界 junction/symlink、内容变化拒绝、LF/CRLF 和再次归档 |
| 私人素材名称出现在公开元数据 | 五个本地条目文件名改为中性编号，同步脱敏 README 和旧验收文档；原始映射只在忽略目录保留 | 新断言在原清单上五项失败，在新清单及相邻隐私回归九项通过；不改音频或 Git 历史 |
| 隔离安装配方展开路径过长 | 深层目录下 `packaging\..` 增加路径长度，重新编译失败；QA 配方改用等价绝对 payload 路径 | 真实 PowerShell helper 回归修前失败/修后通过，完整升级另行核验 |

没有新增 DSP 算法、生产依赖、权重或必需工程字段；没有改默认音色、采样规格或导出格式。不把可靠性修复宣传为无对照测量的速度/内存/音质提升。

## 3. 验证方法与已取得证据

### 不可变快照与数据边界

开始时工作区同时存在另一会话的未暂存修改。本轮先把明确属于本轮的文件加入索引，再通过 `git checkout-index` 导出 `.audit/evolution-051/source/`，从快照测试和构建；不覆盖、删除或误提交并行文件。设置页和归档补充由所有者明确冻结交接后复审集成，再重新验证最终快照，不沿用较早结果。

模型回归复用预先存在、固定 revision 和 SHA-256 的本地 ONNX 缓存；没有下载大型权重。音频测试使用合成夹具与仓库公开 CC BY 4.0 FLEURS 普通话片段；没有上传、提交或重新分发私人歌曲。

| 阶段 | 实际结果 | 本地原始证据（不公开绝对路径） |
| --- | --- | --- |
| 开始前完整基线 | 独立 testcase 469 项：468 通过、1 跳过，0 失败/错误；JUnit 汇总字段为 473；221.901 秒 | `.audit/evolution-051/baseline/results.xml` |
| 五个新回归文件及相邻安全回归 | 77 项通过，0 跳过/失败/错误；16.414 秒 | `.audit/evolution-051/review-after.xml` |
| 主线二审修正后的完整隔离快照 | 独立 testcase 519 项：518 通过、1 跳过，0 失败/错误；JUnit 汇总字段为 523；321.364 秒 | `.audit/evolution-051/final-results.xml` |
| 集成设置、白名单及隐私修复后的完整快照 | 独立 testcase 549 项：546 通过、3 跳过，0 失败/错误；JUnit 汇总字段为 553；225.975 秒 | `.audit/evolution-051/integrated-results.xml` |
| 最终完整快照／独立模型目录 | 收集与独立 testcase 均为 **550 项：547 通过、3 跳过，0 失败/错误**；312.888 秒、退出码 0；真实模型、歌曲 CLI 和证据脚本实际执行 | `.audit/evolution-051/release-isolated-results.xml`、`release-isolated-pytest.log`、`release-collected.log` |
| 安装配方新增独立回归 | 真实 PowerShell helper：修前失败、修后通过；不安装程序的合成配方单测 | `.audit/evolution-051/installer-path-before.xml`、`installer-path-after.xml` |
| Python 编译与差异空白检查 | compileall、`git diff --check` 通过 | 对应本地运行日志 |
| 依赖兼容性 | `uv pip check`：33 个已安装包兼容；未为没有 pip 而重建环境 | 本地命令输出 |
| 已知漏洞审计 | pip-audit 2.10.0：31 个适用锁定依赖，已知漏洞列表为空 | `.audit/evolution-051/dependency-audit.json` |
| 集成后 Windows Freeze | 完成；冻结程序 `--verify-package` 为 PASS，报告版本 0.5.1；WAV/FLAC/MP3/AAC 实际编码、运行库加载与缓存模型推理通过 | `.audit/evolution-051/build-freeze-integrated.log` |
| 原生 Qt 双主题 | 深色逻辑 1024×768、浅色 1280×790；有效像素比 1.25；各捕获 91 个状态，errors 均为空 | `.audit/evolution-051/ui-dark/uiux.json`、`ui-light/uiux.json` |
| 真实 0.5.0→0.5.1 升级及卸载 | 已下载三份上一正式版资产并核对 Release SHA-256；隔离 AppId 重建/安装、恢复 457,758 帧、安装版与便携版真实 DirectML/四格式检查均 PASS；设置/工程/夹具三个文件哈希不变，卸载 PASS | `.audit/evolution-051/previous-release.json`、`upgrade-summary.json`、`upgrade-verification-fixed.log` |
| 最终源码与便携 ZIP 隐私复核 | 源码 225 成员、便携连同嵌套 ZIP 共 906 成员；已知私人标识命中为零，未批准媒体/权重/凭据为零；只放行固定 FLEURS 和与运行环境完全一致的公共 CA 证书包 | `.audit/evolution-051/archive-final-verification.json` |
| 实际源码 ZIP 解包验收 | 24 项定向回归：22 通过、2 项文件符号链接权限跳过；再次归档的 225 个成员内容完全一致 | `.audit/evolution-051/sourcekit-final-targeted.xml`、`sourcekit-final-verification.json` |
| 最终发行目录暴露面 | 573 文件、241 二进制；与原始基线相比无新增或加重的发现编号，不等于零风险 | `.audit/evolution-051/exposure-package-final.json` |

主线快照唯一跳过是 `test_report_rejects_symbolic_link_alias`；集成后另有源码文件链接及 LICENSE 链接两项因 Windows 创建符号链接权限不足而跳过。没有删除测试；目录 junction 回归实际执行通过。真实模型测试在上述全套中启用，不应写成缺测。

最终 XML 的 JUnit 汇总 `tests` 字段为 554，但实际收集列表与独立 `testcase` 节点均为 550；不能把多出的 4 计为额外通过用例。上表早期全量同样按独立节点复核并校正，不沿用汇总字段推算通过数。首次最终回归有 1 项歌曲 CLI 因共享模型目录的使用锁冲突失败，原始 `release-results.xml` 和日志保留。随后把已校验权重复制到本轮新建的独立目录，逐文件确认 SHA-256 与固定模型配置一致，再从同一源码快照完整重跑通过；不下载权重、不删除锁、不放宽锁或测试断言。

初始失败及修正证据分别保留在 media/recent/update/model-storage/review 等 before/after XML 中；早期完整快照和第一轮 Freeze 已被后续修正取代，不能用作最终版本的发行凭据。此前独立只读二审确认先前五项 P2 已解决，在其明确复核范围内无新增 P0–P2；二审是代码复核，不冒充额外一次全套执行。

### 发行边界

Freeze 通过不等于安装/升级验收通过，测试通过也不等于主观听审。上述隔离升级已完成；初次 QA 配方深层路径编译失败的日志保留，修正为等价绝对 payload 路径后完整重跑通过，没有跳过安装、恢复、推理或卸载。正式发行还须核验最终资产、远程 main 与四平台 CI，以及精确版本的更新通道。后续结果必须基于实际收据，不能预填“已发布”。

官方工作流保留 `publish`、确切 `confirm_tag`、本版本 `listening_approved` 和 `accept_limitations` 门禁；0.5.0 的批准不能自动用于 0.5.1。当前不宣称 0.5.1 已正式公开。

## 4. 后续 P0–P3 路线

| 优先级 | 方向 | 完成标准/约束 |
| --- | --- | --- |
| P0 | 数据损坏、密钥泄露、不可恢复覆盖 | 本次明确审阅范围未确认此类未解决阻碍；若新发现则停止稳定发布，先修复并保留失败测试 |
| P1 | 最终发行闭环和并行修复交叉验收 | 干净快照全量、真实旧版升级/卸载、源码隐私核验；主分支与资产 SHA 可对应；不得伪造听审批准 |
| P1 | 长音频资源预算 | 测冷/热耗时、峰值 RAM/显存、磁盘和取消延迟；先实测再考虑分段/流式化；不把 memmap 等同全链路流式 |
| P2 | 独立计量与设备实机 | 用独立公开基准验证响度/真峰值；Win10、实体设备热插拔、跨屏 DPI、低内存；新增大型下载需另行同意 |
| P2 | 安装器系统签名与发行权限分离 | Authenticode 证书/费用与凭据配置需明确授权；不把 Ed25519 清单验签当系统签名 |
| P3 | 多模型/插件扩展 | 先核实代码、权重、素材分别的许可及资源预算；不盲目引入 PyTorch/TensorFlow 或 GPL 实现 |

[安全暴露面与误报解释](SECURITY-051.md)另列证据、无法靠客户端加固解决的边界和修复顺序。
