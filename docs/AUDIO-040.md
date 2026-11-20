# 0.4.0 真实整曲本机处理记录

**状态：两首音频完成本地 DirectML 推理、分轨、混音、母带、FLAC 编码和回读测量；人工听审未完成，分离音质不予结论。**

## 授权与隔离

两首 MP3 来自用户明确指定的本机桌面参考文件，只用于当前任务的本地处理。没有上传、公开分发、提交 Git 或用于模型训练。模型未下载：使用已有本地固定版 Spleeter 权重。输入/输出/会话指标仅保存在 Git 忽略目录 `.audit/040-real-final/`（第一次运行保留在 `.audit/040-real/`）。文件名、输入与输出 SHA-256 及完整逐曲证据均在该本地目录的 JSON 文件中。

## 环境与方法

- 实机为 Windows 11 专业版 x64 Build 26300；版本 API 字符串 `Windows-10-10.0.26300-SP0` 不代表完成 Windows 10 验收。Python 3.11.18，NVIDIA GeForce RTX 5060 Laptop GPU 8,151 MiB，ONNX Runtime `DmlExecutionProvider`。
- 缓存模型固定提交 `7001ba316a615cacddb3f9ef3ec416661a277e26`。两个模型 SHA-256：
  - `vocals.onnx` `bdc16ab6bf6117ddd4842c19e80e40e2be188fc555295064d424616b0224ac97`
  - `accompaniment.onnx` `671ace17acd3720674a2bc14de32ac6292453dec20d9eb0ba4255d4ad8e3d8c0`
- 两首均选择「自然还原 + 保守母带」，分离后测量、保守人声 EQ/动态处理、有限伴奏 EQ/平衡，使用现有 Studio 双轨总线与最终峰值保护，导出 FLAC 24-bit。
- 最终实际运行：`python scripts/accept_song.py <本机文件> --output-dir .audit/040-real-final/output --device DirectML --target natural --master conservative --format flac --provenance ... --rights ... --evidence .audit/040-real-final/<id>.json`。
- 端到端耗时从进程启动到输出回读测量（含解码和模型加载），非纯 GPU 推理时间。输入处理前后 SHA 一致，权重未修改。

## 处理前后客观数据

| 素材 | 输入规格/时长 | 输入 LUFS-I / dBTP | 输出格式/时长 | 输出 LUFS-I / dBTP | 帧数一致 | 实际 Provider | 端到端时间 |
|---|---|---|---|---|---|---|---:|
| 月色倒映在西湖 - 王斩.mp3 | MP3，44.1 kHz，双声道，104.882 s | **−3.97 / +3.48** | FLAC 24-bit，44.1 kHz，双声道，104.882 s | **−15.00 / −6.62** | 是，4,625,280 帧 | DirectML | 18.620 s |
| 寒冬向北 - 王斩.mp3 | MP3，44.1 kHz，双声道，117.070 s | **−4.65 / +3.34** | FLAC 24-bit，44.1 kHz，双声道，117.070 s | **−15.00 / −6.91** | 是，5,162,772 帧 | DirectML | 20.574 s |

两个源文件解码后已出现超过 0 dBTP 的峰值，属于源响度/峰值很高的成品；本流程按保守目标降低电平，没有继续追求更响。导出回读未报告削波或峰值门限违规；母带留出的峰值空间（约 4.9 dB）是这两首素材的实际结果，并非目标建议所有作品都采用 −15 LUFS。源音频中已有的削波/失真、分离伪影均不能通过单纯电平处理还原。

分离前后对齐，各 2 轨长度与输入一致；报告 `reconstruction_error_db = −120 dB` 是数值下限，源自伴奏定义为输入减去人声后再相加的构造。**它不是 SDR/SI-SDR，不是串音指标，也不能说明人声是否分离干净。**

## 听审与验收限制

- 没有人工播放、等响盲听、分项评分或制作人批准；目前不能声称人声自然、清晰、厚实、融合良好，也不能称为“专业母带已验收”。
- 没有独立的真人干声、已知干声+伴奏混合真值对照，暂不能量化源分离泄漏。两首参考文件均是已混合/压缩/带空间效果的完整成品，不能作为“独立干声”测试。
- 需要音频制作人实际监听 **原曲 A vs 处理后 B**（播放响度匹配、相同区间），分别记录人声清晰度/音色/齿音/伪影、伴奏保真/融合、低频/高频、立体声兼容性、峰值或失真，以及监听设备/区间/偏好原因。听审未做前须保留此门禁。

## 私有逐曲记录（被 `.gitignore` 忽略）

- `.audit/040-real-final/yuesey.json` + `.audit/040-real-final/yuesey.stdout.json` — 含源文件和 FLAC 成品 SHA-256、源和导出格式、逐轨 DSP 测量、母带结果、输入不变核验与授权说明。
- `.audit/040-real-final/handong.json` + `.audit/040-real-final/handong.stdout.json` — 同上。
- 最终媒体事务代码再次复测于 `.audit/040-release-review/real/`：输入哈希不变，月色输出 SHA `19aa3ff0…`、寒冬 `57f61345…` 与首轮一致，LUFS/TP 保持 −15.00 / −6.62 与 −6.91，`separation.status=verified`、provider DML。
- 最终复测新增内容哈希绑定，`separation.status=verified`，防止替换同长度素材后继续显示旧模型/重建证据。两次运行最终 FLAC 哈希一致；没有据此宣称听感或性能改进。
- 哈希及本机绝对路径仅存本机未跟踪审计材料中，不复制到 Git 跟踪的报告。人声/伴奏 32-bit 暂存 WAV 与最终 FLAC 位于 `.audit/040-real-final/output/`，**不进 Git**。