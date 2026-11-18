# 原项目审计（2026-11-18）

起点为干净 main / 3dd78476dac3987d04fadfa5fd932cf15700579e，SSH origin 为 yuchen0x1/VoxMaster-AI；公开仓库，管理员权限。仅一个历史提交与 v0.1.1 Release，包含安装器、便携包、源码、Qt 对应源码和校验文件。没有 Actions、分支保护、Secrets/Variables、未结 Issue/PR、Pages；Issues 和 Wiki 已启用，Discussions 未启用。Secret Scanning 与 Push Protection 已启用。没有项目级 LICENSE，保持作者现状。

## 原功能与模块覆盖

| 路径 | 既有职责与必须保留的行为 |
|---|---|
| app / interface / dialogs / settings / visual / dsp_panel / review | Qt 原生主窗口、文件拖放、快捷键、设置、报告、波形频谱、效果器试听与等响 A/B |
| service / jobs | 可取消后台测量与重建；只把完成结果提交 UI，取消保留原会话 |
| audioio / playback / hardware | PyAV 有限格式解码、44.1k 双声道总线、临时映射、原子禁止覆盖导出、PortAudio 监听、设备失效回退与设备身份解析 |
| analysis / acoustics / quality / segments | LUFS/真峰值、音高/动态、声学证据、分类置信度、分段自动化与最终缓冲复测 |
| engine / presets / pitch / tail011 / pitch_tail_editor | 18 风格、降噪/EQ/压缩/齿音/空间/M/S、音高与尾音修改、有限值与参数边界 |
| reference | 同类发声匹配、空间证据、有界调整与恢复原参数 |
| studio / studio_session / studio_effects / studio_balance / studio_timeline / studio_mix_dialogs | 三轨非破坏剪辑、帧坐标、路由、效果链、包络、侧链/避让/平衡、撤销与监听同步 |
| storage | schema=1 JSON、大小限制、原子保存、版本备份、相对素材和重定位，无数据库 |
| models / models_store / models_runtime / models_dxgi | 固定双模型、续传与哈希、文件锁与迁移、独立可终止推理进程、DirectML/CUDA/CPU 路由 |
| packaging / scripts | PyInstaller onedir、专用 LGPL FFmpeg/LAME 动态库、Qt 源码与通知、Inno 用户安装、包自检、音频与故障探针 |
| tests | 105 项原回归、真实普通话样本；另有本地音频语料和历史硬件/压力证据 |

检查包含目录清单、全部主模块符号与依赖边界、关键业务实现、既有测试断言、构建/授权链以及远程仓库 API。源码不等于实体设备验收，历史 docs/evidence-011 不作为本轮新结果。

## 本轮前基线与风险

使用恢复的固定依赖环境运行未修改源码：103 passed、2 skipped，265.60 秒；外层进程退出码为 1，虽无 pytest 失败摘要仍不能标记完整 PASS。未设模型权重导致两项跳过；后续回归显式使用已有本地权重。Windows 原生启动另行重新捕获，详见交付记录。

主要缺口：无自动化 CI/CD 和保护；版本在三处重复；更新只信任自定义清单版本字符串，未有签名安装链；依赖强制 Windows DirectML/PE 包；非 Windows 目录和默认设备文案未适配；暂无批处理接口；整仓授权未明确。真实安装器未签名、移动/Web 没有产品架构，不能以 Qt 跨平台能力替代验收。

本轮不改变品牌、仓库或许可，不重写音频引擎，不引入上传服务、数据库或第三方插件。细分平台与阻塞见 PLATFORMS，研究和候选见 RESEARCH-020，实际执行状态见 DELIVERY-020。
