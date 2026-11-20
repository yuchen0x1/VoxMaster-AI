# 0.4.0 上游工具、商业产品与许可分层研究

观察时间：2026-11-20（Asia/Shanghai）。本轮只读取可公开打开的官方仓库、官方产品页、官方手册、软件包元数据和论文正文；没有下载任何模型权重、安装器或测试音频，没有运行分离/变调/母带处理，也没有进行试听。因此本文不提供“哪个更好听”的结论，厂商与论文中的性能数字均标注为发布方声明，未在本机复现。

## 证据等级

| 等级 | 含义 | 本轮用法 |
|---|---|---|
| A | 官方机器可读接口或正文：GitHub API、PyPI JSON、DataCite、JOSS PDF、官方许可证文件 | 用于版本、日期、许可原文和条款引用 |
| B | 官方页面或官方手册的人工读取 | 用于产品能力、平台、格式和活动日期 |
| C | 搜索结果摘要，仅用于定位官方页面 | 不单独支撑结论；正文中的关键结论均回到 A/B |
| 未知 | 官方未公开、页面不可达或条款存在冲突 | 在“未知项”中单列，不推断为可用 |

证据限制：iZotope 产品页在本次访问中返回 HTTP 429，Nectar 的能力与版本以官方手册和官方 release notes 为准；Antares 的 Pro 11 release notes 页面连接超时，未取得正文，因此不记录其具体版本号；Hugging Face API 超时，Applio 数据集卡在浏览器中读取。GitHub 仓库的 `license` 元数据可能来自历史检测，不能替代许可证正文，本文对 UVR 单独核对了默认分支文件。

## 结论摘要

- **代码许可清楚、权重许可不清楚**是源分离领域的常态：Demucs 代码 MIT，但维护者明确表示权重许可不清晰；Spleeter 论文称代码与预训练模型均为 MIT，README 只称代码 MIT，公开 issue 仍未关闭；UVR 的 README 称 MIT，但默认分支已没有 LICENSE 文件。
- **Applio** 是少数在 README 中同时声称代码和权重 MIT 的项目，但另有 Terms of Use，训练数据卡为 ODC-By，VCTK 0.92 为 CC BY 4.0；“MIT 声明”不能替代逐模型、逐数据集的权利核验。
- **Matchering 与 Audacity 是 GPL 系**：Matchering 为 GPL-3.0，Audacity 为 GPLv3（多数文件 GPLv2-or-later，另有第三方与 VST3 相关例外）。两者适合作为流程与文档参考，不应把代码链接进闭源发行物；独立工具的法律边界需专业意见，不能由本文判定。
- **Nectar、AutoTune、REAPER 是闭源商业产品**：公开条款未授予代码/权重再分发、子许可、修改或嵌入权；REAPER 另以 Distribution Agreement 允许原样分发安装器，但不覆盖“集成进另一个应用”。
- **VST3 SDK 已为 MIT**，但旧版本、VST2 和商标/标识规则分开；SDK 许可不改变第三方插件的自身许可。当前项目没有 VST3 宿主，仍维持延期。
- 本轮不改变现有分离链、参考匹配链或发行范围；建议把“代码/权重/数据/宿主 SDK”四类许可字段纳入模型中心与发布检查，而不是用一个总许可证概括。

## 开源项目对照

| 项目 | 能力与定位 | 代码许可 | 权重 / 数据 | SDK / 运行库 | 可核验活动 | 证据 |
|---|---|---|---|---|---|---|
| [Ultimate Vocal Remover GUI (UVR)](https://github.com/Anjok07/ultimatevocalremovergui) | Windows 自包含分离 GUI；MDX-Net、VR、Demucs；UVR6 预告模型目录、ensemble 与 CLI | README 声称 MIT；但默认分支无 `LICENSE` 文件，2022-12-19 有 “Delete LICENSE” 提交；GitHub API 元数据仍显示 MIT | README 称核心开发者训练了除 Demucs v3/v4 4-stem 外的模型，并要求第三方开发者署名；未找到逐模型许可 | 无公开 SDK；自带 Python/模型运行时 | 最新稳定 release 为 v5.6（2023-09-26）；最近提交 2026-10-06 为 README 更新；UVR6 公告 2026-12-11，尚未发布 | A（提交/文件）、B（官网/issue） |
| [Applio](https://github.com/IAHispano/Applio) | RVC 语音转换、Gradio UI、插件、训练与 ONNX 推理/导出 | MIT（`LICENSE`） | README 明确声称“源代码和模型权重”均为 MIT；另有 `TERMS_OF_USE.md`；逐 checkpoint 未核 | 无独立 SDK；依赖 PyTorch/ONNX 生态 | release 3.7.2（2026-11-19），同日提交；新增完整 ONNX 推理/导出与训练队列进度 | A |
| [Demucs](https://github.com/facebookresearch/demucs) | 4/6 stem 源分离；CLI/API；Hybrid Transformer | MIT | 维护者 2026-10-26 明确：代码 MIT，**权重许可不清晰**；6-source 仅用 Meta 内部数据训练，可能适用 CC-NC-BY；MUSDB 含仅限研究的数据 | PyTorch；无商业权重授权 | 原仓已归档，最后提交 2023-11-16；活跃 fork [adefossez/demucs](https://github.com/adefossez/demucs) 最后提交 2026-10-26；PyPI 4.1.0（2026-07-11） | A |
| [Spleeter](https://github.com/deezer/spleeter) | 2/4/5 stem；TensorFlow；CLI/Docker | MIT | 论文正文称“source code and pre-trained models ... distributed under a MIT license”；README 只称代码 MIT；[issue #959](https://github.com/deezer/spleeter/issues/959) 仍 open，公开评论中未见维护者澄清；训练数据为 Deezer 内部数据，因版权不能发布 | TensorFlow；无商业权重授权文本 | README 提交 2026-10-28；最新 release v2.3.0（2021-09-03）；PyPI 2.4.2（2025-04-03） | A |
| [Open-Unmix](https://github.com/sigsep/open-unmix-pytorch) | 4 stem 研究基线；LSTM；非实时 | MIT | README 明确 `umxl` 权重仅限非商业（CC BY-NC-SA 4.0）；其余 checkpoint 未逐项核 | PyTorch；研究用途 | v1.3.0（2024-04-16），此后低活动 | A |
| [Matchering](https://github.com/sergree/matchering) | 参考匹配/母带；按参考的 RMS、频率响应、峰值和立体声宽度匹配 | GPL-3.0 | 无预训练权重；使用用户提供的 target/reference | Python 库、Docker、ComfyUI 节点 | 最近提交 2026-10-07（RnbJesus Band support）；PyPI 2.0.6（2022-10-19），多年无新 release | A |
| [Audacity](https://github.com/audacity/audacity) | 音频编辑器；Noise Reduction、Macros、Nyquist、插件管理、多轨导出 | GPLv3；多数源文件 GPLv2-or-later；`/au3/lib-src` 与 VST3 相关代码有例外 | 无模型权重；文档为 CC BY 3.0（另有说明除外） | Nyquist 脚本；VST 支持；无公开 SDK 授权 | 4.0.2（GitHub release 2026-11-02；官网当前版本 4.0.2）；2026-11-20 仍有提交 | A/B |
| [VST 3 SDK](https://github.com/steinbergmedia/vst3sdk) | 插件 SDK / 宿主开发 | MIT（3.8.x）；旧版本沿用各自条款；VST2 需 2018-10 前签署的协议 | 无权重/数据 | VST3 SDK；商标与标识规则另行 | 3.8.1 提交 2026-08-11 | A/B |

补充：Demucs README 报告 `htdemucs` 在 MUSDB HQ 测试集上的 SDR 为 9.00 dB，并称使用稀疏注意力与逐源微调可达 9.20 dB。这是论文/仓库作者的公开指标，本轮未复现，不作为听感或“优于某工具”的证据。

## 商业产品对照

| 产品 | 能力与定位 | 许可结构 | 可核验活动 | 可嵌入性 | 证据 |
|---|---|---|---|---|---|
| [iZotope Nectar 4](https://www.izotope.com/en/products/nectar.html) | 人声链：Vocal Assistant、Auto-Level、Voices、Pitch、Audiolens 参考；Advanced 含 13 个独立插件 | 闭源；[官方 EULA](https://www.izotope.com/en/software-license-agreement) 由 Boris FX 授予单机运行权；禁止再分发、子许可、出租/出借、修改与反向工程；未提供 SDK/嵌入授权 | 官方 release notes 显示 4.2.0（2026-08-18），Advanced/Standard 均更新 | 不可嵌入；不可随产品分发 | B（手册/ release notes/EULA） |
| [Antares AutoTune](https://www.antarestech.com/products/auto-tune) | 自动音高修正；Advanced 为实时自动旗舰；Pro 11 保留 Graph Mode 逐音符编辑 | 闭源；官方支持页引用 EULA 第 5 条：许可不可转让，禁止子许可、分发或转让；完整 EULA 仅随安装提供，公开页未给出全文 | AutoTune Advanced 于 2026-09-24 发布；同日 AutoTune 2026 更名为 AutoTune；Pro 11 仍为手动编辑产品 | 不可嵌入；无公开 SDK | B（产品页/博客/支持页） |
| [REAPER](https://www.reaper.fm/) | DAW；ReaScript（EEL2/Lua，Python 需另装）、OSC、扩展生态 | 闭源商业许可：个人/小规模商业 60 美元，其他商业 225 美元；[Distribution Agreement](https://www.reaper.fm/dist-agreement.php) 仅允许原样分发 7.0–7.999 安装器，含条件与季度申报，明确不覆盖集成进其他应用 | 7.86（2026-11-13） | 不可嵌入；可作为外部工作流/自动化参考 | B |

Nectar 官方手册把 Advanced 的 13 个独立插件格式写为 VST3、AUv2、AAX only；这是插件格式事实，不等于授予第三方宿主或再分发权。Antares 产品页列出 macOS 14+、Windows 10/11，但未在可读页面列出 VST3/AU/AAX 的具体格式清单，本文不补猜。Antares 官方 “software attributions” 页列出 JUCE（ISC）、libsamplerate（BSD-2-Clause）、ONNX Runtime（MIT）等组件通知；这些是第三方组件声明，不是 AutoTune 本体的再分发许可。

## 许可分层

### 代码

- **MIT**：Applio、Demucs、Spleeter、Open-Unmix、VST3 SDK（3.8.x）。MIT 只覆盖对应代码，不自动覆盖权重、训练数据、商标或第三方组件。
- **GPL-3.0**：Matchering。分发衍生/组合作品通常需要按 GPL 提供相应源代码；内部使用与独立工具的分发边界需法律意见，本文不作判定。
- **GPLv3**：Audacity。多数文件为 GPLv2-or-later；`/au3/lib-src` 与 VST3 相关代码有例外，文档为 CC BY 3.0。把 Audacity 代码链接进闭源应用与“独立进程调用”不是同一法律问题，不能混为一谈。
- **声称 MIT 但缺许可证正文**：UVR。README 仍链接 `LICENSE`，但该文件已于 2022-12-19 删除；GitHub API 的 MIT 元数据不能替代实际许可文本。对外分发前必须取得维护者书面确认或恢复许可证文件。
- **闭源**：Nectar、AutoTune、REAPER。公开条款均未授予再分发、子许可、修改或嵌入权。

### 权重

- **Applio**：README 声称代码与权重均 MIT；这是本项目目前看到的、范围最宽的自述，但仍需逐 checkpoint 核对来源、训练数据与 Terms of Use。
- **Demucs**：维护者明确“权重许可不清晰”；6-source 可能为 CC-NC-BY；`htdemucs`/`htdemucs_ft` 未获明确商业授权。不能因代码 MIT 而推定权重可用。
- **Spleeter**：论文称代码与预训练模型均为 MIT；README 只称代码 MIT；issue #959 仍未关闭。两种表述存在范围差异，商业分发前应取得维护者确认。当前项目使用的转换权重另有来源记录，见 [MODELS.md](MODELS.md)，其独立商业分发条款仍未明确。
- **Open-Unmix**：`umxl` 权重为 CC BY-NC-SA 4.0，仅非商业；其余 checkpoint 未逐项核。
- **UVR**：README 要求使用其模型时署名，但未提供逐模型许可文本；不能把“署名要求”当作完整许可。
- **Matchering / Audacity / VST3 SDK / REAPER / Nectar / Antares**：不涉及本项目要引入的预训练权重；商业产品本身不含可再分发权重授权。

### 数据

- **MUSDB18 / MUSDB18-HQ**：官方数据集页说明曲目仅限学术用途，维护者人工审核 Zenodo 访问请求；部分曲目为 CC BY-NC-SA，部分来自 Native Instruments，100 首 DSD100 曲目的权利需回到原始 Mixing Secrets 库。Demucs、Open-Unmix 的训练/评测与该数据集相关，不能把“模型可下载”理解为“训练数据可商用”。
- **VCTK 0.92**：DataCite 记录为 CC BY 4.0，出版者为 University of Edinburgh CSTR；使用时需保留署名。早期 VCTK 版本条款可能不同，不能拿 0.92 的许可覆盖旧镜像。
- **Applio-Dataset**：Hugging Face 数据集卡显示 ODC Attribution License (ODC-By)，并引用 University of Edinburgh CSTR 作为许可方；具体数据来源仍需逐项核对。Applio 的模型训练还涉及其他公开数据集，README 未给出逐数据集清单。
- **Spleeter 训练数据**：论文明确因版权原因不能发布训练数据，训练使用 Deezer 内部数据集（包括 Bean）。这意味着权重的“MIT”声明无法通过数据许可链自动验证。
- **用户录音/参考曲**：本项目只应在用户提供且有权使用的素材上处理；参考匹配不应把参考音频混入成品，这一点与现有参考流程一致。

### SDK / 宿主 / 运行库

- **VST3 SDK**：3.8.x 为 MIT；旧版本沿用旧条款；VST2 二进制分发需要 2018-10 前签署的 VST2 协议；商标/标识使用规则另行，官方 FAQ 未在可读段落给出完整商标许可。MIT 只覆盖 SDK 代码，不覆盖第三方插件。
- **REAPER ReaScript/EEL2**：官方页面称 EEL2 为 “open source” 但未点名许可证；扩展 SDK 的再分发条款在可读页面中未找到。不能把 REAPER 的脚本能力当作可嵌入 SDK。
- **Audacity Nyquist**：随 GPL 应用分发；脚本/插件条款随 Audacity 整体许可，不应单独抽取出闭源组件。
- **Matchering**：作为 GPL-3.0 Python 库，链接/分发方式会影响义务；仅把它当作算法与指标参考更稳妥。
- **Nectar / Antares**：未提供公开 SDK、嵌入授权或再分发许可；第三方组件通知不等于产品许可。

## 未知项与冲突

| 项目 | 未知或冲突 | 影响 | 需要的证据 |
|---|---|---|---|
| UVR | README 称 MIT，但默认分支无 LICENSE；逐模型许可缺失 | 不能把 UVR 代码或模型当作已清除权利的商用素材 | 维护者书面许可、恢复的 LICENSE、逐模型许可清单 |
| UVR 模型 | 核心开发者训练与第三方 Demucs 模型混合；README 只要求署名 | 即使代码许可恢复，模型仍可能分层 | 每个模型的文件、来源、训练数据、许可 |
| Demucs | 权重许可“不清晰”；6-source 可能 CC-NC-BY；MUSDB 学术限制 | 不能随商业产品分发权重 | Meta/作者对每个 checkpoint 的明确授权 |
| Spleeter | 论文称权重 MIT；README 只称代码 MIT；issue #959 未关闭 | 现有依赖的长期商业分发存在解释风险 | 维护者对 issue 的公开答复或新 LICENSE 说明 |
| Applio | 权重 MIT 自述；Terms of Use 另有伦理/使用条件；数据集 ODC-By 与 VCTK CC BY 4.0 | 逐模型商用仍需核对，不能只看 README | 每个 checkpoint 的训练数据与许可、Terms 的法律审阅 |
| Open-Unmix | `umxl` 非商业；其余 checkpoint 未逐项核 | 只能作研究基线 | 逐 checkpoint 许可 |
| MUSDB18 | 学术用途、人工审核、曲目许可混合 | 训练/评测数据不能默认商用 | 原始曲目清单与权利方许可 |
| Nectar | 公开 EULA 可读，但第三方组件与各 edition 的完整条款未逐项核 | 不能嵌入或再分发 | 安装包内完整 EULA、第三方 notices、书面 SDK 授权（若有） |
| Antares | 完整 EULA 仅随安装提供；公开页未列全部插件格式；无公开 SDK | 不能嵌入；格式兼容需实测 | 安装后的 EULA 全文、官方格式清单、书面授权 |
| REAPER | ReaScript/EEL2 与扩展 SDK 的许可未在可读页面明确 | 只能作为外部工具参考 | SDK 包内 LICENSE、Cockos 书面说明 |
| Audacity | VST3 相关代码与 `/au3/lib-src` 为例外；文档 CC BY 3.0 | 不能把“GPLv3”简单套到所有文件 | 逐文件许可、发行时对应源代码与 notices |
| Matchering | GPL-3.0 与闭源分发的边界 | 直接链接/打包风险高 | 法律意见；或仅复用独立测量的思路 |
| VST3 SDK | 商标/标识规则、旧版 SDK、VST2 协议 | 宿主实现可做，但品牌与旧插件兼容需单独处理 | Steinberg 商标指南、VST2 协议、逐版本 SDK LICENSE |

## 对本项目可用与不适用

| 来源 | 可吸收 | 不吸收 | 理由与落点 |
|---|---|---|---|
| UVR | 模型目录/搜索、ensemble 的 UX、批量 CLI 的产品思路（UVR6 尚未发布） | 代码、模型权重、安装器 | 许可链不完整；只作为产品形态参考，不进入发行物 |
| Applio | 训练/推理队列的分段进度、ONNX 导出与模型注册思路 | 语音转换功能、权重、UI 素材 | 与离线喊麦调音定位不同；声音克隆涉及同意与权利风险 |
| Demucs | 分块、重叠窗口、内存策略的设计参考 | 预训练权重 | 权重许可不清晰；现有 Spleeter 分离链已满足离线双轨需求 |
| Spleeter | 当前固定双模型 + SHA-256 的供应链做法 | 未澄清的额外权重 | 保持现有依赖；在模型中心补充“代码/权重/数据许可未知”字段 |
| Open-Unmix | 作为研究对照的分轨基线 | `umxl` 权重与任何商用分发 | 非商业权重；非实时；不替换现有链 |
| Matchering | “按参考测量 RMS/频率响应/峰值/立体声宽度”的指标维度 | GPL-3.0 代码、Docker 镜像 | 本项目已有参考测量与有限参数匹配；独立实现测量思路，不复制代码 |
| Audacity | Noise Reduction 的“先取噪声轮廓”流程与官方限制说明 | GPL 代码、Nyquist 脚本、VST3 例外代码 | 可用于界面提示与验收口径；不链接进闭源应用 |
| REAPER | 外部 DAW/ReaScript/OSC 工作流的兼容性参考 | 应用本体、安装器、扩展 SDK | Distribution Agreement 明确不覆盖集成；只作为用户外部工具 |
| VST3 SDK | 未来宿主原型的 MIT SDK 与插件扫描/状态保存研究 | 当前发行物中的 VST3 宿主承诺 | 0.4.0 仍延期；先确认“宿主还是插件”，再评估许可、进程隔离与实时预算 |
| Nectar 4 | Vocal Assistant 的“先粗后细”、Auto-Level、Voices、参考音色的交互分层 | 代码、插件、预设、品牌/图标、营销用语 | 闭源且禁止再分发；只做功能与信息架构参考 |
| AutoTune | retune speed、Humanize、Flex Tune、formant、音阶/键盘等控制 taxonomy | 插件、算法实现、商标、<1 ms 等厂商性能声明 | 闭源且不可嵌入；只用于参数命名与可解释性设计 |

## 不作为听感结论的声明

- 本文没有试听任何工具的输出，也没有比较“谁更自然、谁更清晰、谁更适合喊麦”。现有项目的听审记录仍以 [LISTENING-011](LISTENING-011.md) 为准，不能拿本轮资料替代。
- Demucs 的 SDR 9.00/9.20 dB 是作者在 MUSDB HQ 上的报告值，本轮未复现；它不能直接外推到中文喊麦、混响人声或本项目导出链。
- Antares 页面的 “Live < 1 ms” 是厂商声明，未在本机验证；本轮不把它写成事实。
- Nectar/Antares 的 “professional-quality” 等营销描述不作为音质证据；本文只记录其公开功能、格式和许可。
- Applio 的 “high-quality voice conversion” 是项目自述；本文不据此判断任何音频结果。

## 建议动作（研究结论，不含实现）

1. **模型中心增加四类许可字段**：代码、权重、训练数据、运行时/SDK；允许值为 `verified`、`claimed`、`unknown`，并保留来源 URL 与核对日期。当前 Spleeter 条目应把“权重商业分发条款未明确”显式展示，而不是只显示 MIT。
2. **商业分发前做权重清单**：逐个 checkpoint 记录来源、SHA-256、训练数据、许可和书面确认；Demucs、UVR、Open-Unmix 的权重在没有明确授权前不得进入发行物。
3. **参考匹配保持“测量不入成品”**：沿用现有参考测量与有限参数匹配；可借鉴 Matchering 的指标维度，但不复制其 GPL 代码，也不把参考音频写入导出。
4. **VST3 继续延期**：若未来研究，先做“宿主”原型，使用 MIT 的 VST3 SDK；同时单独处理第三方插件 EULA、商标和崩溃隔离，不对外承诺 VST3 兼容。
5. **降噪提示采用 Audacity 式边界**：只对稳定背景噪声给建议；噪声过响、变化大或与人声频带重叠时明确提示可能无法满意去除；不把该提示写成效果保证。
6. **发布检查新增“无 GPL/无不明权重”项**：确认发行物不含 Audacity/Matchering 代码、不含 Demucs/UVR/Open-Unmix 权重；保留 Nectar/Antares/REAPER 仅作为外部参考，不打包其任何文件。

## 来源

访问日期均为 2026-11-20。GitHub 条目同时核对了仓库、提交、release、README 或 LICENSE 正文；PyPI 条目读取了 JSON 元数据；论文条目读取了 JOSS 正文 PDF。

### 源分离与语音转换

- UVR 仓库：https://github.com/Anjok07/ultimatevocalremovergui
- UVR README：https://github.com/Anjok07/ultimatevocalremovergui/blob/master/README.md
- UVR 删除 LICENSE 的提交：https://github.com/Anjok07/ultimatevocalremovergui/commit/63a4cb691b0342b1a65807ceb20c06f12f92c682
- UVR v5.6 release：https://github.com/Anjok07/ultimatevocalremovergui/releases/tag/v5.6
- UVR6 开发公告：https://github.com/Anjok07/ultimatevocalremovergui/issues/2399
- UVR 官网：https://ultimatevocalremover.com/
- Applio 仓库：https://github.com/IAHispano/Applio
- Applio 3.7.2 release：https://github.com/IAHispano/Applio/releases/tag/3.7.2
- Applio LICENSE：https://github.com/IAHispano/Applio/blob/main/LICENSE
- Applio Terms of Use：https://github.com/IAHispano/Applio/blob/main/TERMS_OF_USE.md
- Applio 数据集卡：https://huggingface.co/datasets/IAHispano/Applio-Dataset
- Demucs 原仓（已归档）：https://github.com/facebookresearch/demucs
- Demucs 活跃 fork：https://github.com/adefossez/demucs
- Demucs 权重许可澄清提交：https://github.com/adefossez/demucs/commit/829d21890023800713e5dd231c67e43ecc06069b
- Demucs PyPI 4.1.0：https://pypi.org/project/demucs/4.1.0/
- Spleeter 仓库：https://github.com/deezer/spleeter
- Spleeter LICENSE：https://github.com/deezer/spleeter/blob/master/LICENSE
- Spleeter 论文（JOSS）：https://joss.theoj.org/papers/10.21105/joss.02154
- Spleeter 论文 PDF：https://www.theoj.org/joss-papers/joss.02154/10.21105.joss.02154.pdf
- Spleeter 权重许可 issue：https://github.com/deezer/spleeter/issues/959
- Spleeter PyPI 2.4.2：https://pypi.org/project/spleeter/2.4.2/
- Open-Unmix 仓库：https://github.com/sigsep/open-unmix-pytorch
- Open-Unmix LICENSE：https://github.com/sigsep/open-unmix-pytorch/blob/master/LICENSE
- MUSDB18 数据集页：https://sigsep.github.io/datasets/musdb.html
- VCTK 0.92 DataCite 记录：https://doi.org/10.7488/ds/2645
- VCTK 0.92 数据页：https://datashare.ed.ac.uk/handle/10283/3443

### 参考匹配、编辑与宿主

- Matchering 仓库：https://github.com/sergree/matchering
- Matchering LICENSE：https://github.com/sergree/matchering/blob/master/LICENSE
- Matchering PyPI 2.0.6：https://pypi.org/project/matchering/2.0.6/
- Audacity 仓库：https://github.com/audacity/audacity
- Audacity LICENSE：https://github.com/audacity/audacity/blob/master/LICENSE.txt
- Audacity 4.0.2 release：https://github.com/audacity/audacity/releases/tag/Audacity-4.0.2
- Audacity 官方下载页：https://www.audacityteam.org/download/
- Audacity Noise Reduction 手册：https://manual.audacityteam.org/man/noise_reduction.html
- Audacity 手册首页：https://manual.audacityteam.org/
- REAPER 下载页：https://www.reaper.fm/download.php
- REAPER 购买与许可：https://www.reaper.fm/purchase.php
- REAPER Distribution Agreement：https://www.reaper.fm/dist-agreement.php
- REAPER ReaScript：https://www.reaper.fm/sdk/reascript/reascript.php
- REAPER 更新记录：https://www.reaper.fm/whatsnew.txt
- VST3 SDK 仓库：https://github.com/steinbergmedia/vst3sdk
- VST3 SDK LICENSE：https://github.com/steinbergmedia/vst3sdk/blob/master/LICENSE.txt
- VST3 许可 FAQ：https://steinbergmedia.github.io/vst3_dev_portal/pages/FAQ/Licensing.html

### 商业产品

- Nectar 产品页：https://www.izotope.com/en/products/nectar.html
- Nectar 4 手册：https://docs.izotope.com/nectar4/en/index.html
- Nectar 4 Vocal Assistant：https://docs.izotope.com/nectar4/en/assistant/index.html
- Nectar 4 release notes：https://www.izotope.com/pages/release-notes/nectar
- iZotope 软件许可协议：https://www.izotope.com/en/software-license-agreement
- AutoTune 产品页：https://www.antarestech.com/products/auto-tune
- AutoTune Advanced：https://www.antarestech.com/products/pitch-correction/advanced
- AutoTune Pro：https://www.antarestech.com/products/pitch-correction/pro
- AutoTune 更名与 Advanced 发布：https://www.antarestech.com/blog/autotune2026-is-now-simply-autotune
- AutoTune Advanced 介绍：https://www.antarestech.com/blog/introducing-autotune-advanced
- Antares 许可转让政策（引用 EULA 第 5 条）：https://help.antarestech.com/hc/en-us/articles/41113165662228-Antares-Transfer-of-Ownership-Policy
- Antares 第三方组件声明：https://www.antarestech.com/software-attributions
- Antares 服务条款：https://www.antarestech.com/terms-of-service