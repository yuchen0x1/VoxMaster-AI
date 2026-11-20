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
