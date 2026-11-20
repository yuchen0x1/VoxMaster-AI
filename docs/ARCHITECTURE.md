# 架构与数据流

桌面进程运行 Qt Widgets。窗口负责收集输入、调度工作线程及交换已提交的 Session。解码、分析、渲染和编码在后台执行，通过信号返回实际阶段和进度。播放回调读已经准备好的 PCM。分离推理运行在独立可终止的进程中。

| 层 | 文件与职责 |
|---|---|
| 桌面交互 | app.py、interface.py、dialogs.py、visual.py、dsp_panel.py、settings_dialog.py 共同实现主窗口、图形效果器与设备页 |
| 应用服务 | service.py 重建工程，将原音、原始测量、当前调音人声、最终混音和结果测量区分保存。jobs.py 管理可取消后台任务 |
| 读写与监听 | audioio.py 处理 PyAV 解码、重采样、缓存与原子导出。playback.py 向 PortAudio 传递准备好的立体声缓冲 |
| 分析 | analysis.py 执行 K 加权与门限积分、四倍过采样峰值、能量分布、基频与节奏分析。acoustics.py 对瞬态、稳定音段、平顶及尾部衰减给出可复查证据 |
| 调音 | presets.py 提供风格基准。engine.py 根据测量和参考音频修正参数并执行效果链。pitch.py 负责有声段音高校正 |
| 模型 | models_store.py 管理固定版本的下载、哈希、文件锁与迁移。models_runtime.py 管理分块、重叠区、推理子进程与 GPU 失败回退。models_dxgi.py 识别 DXGI 适配器 |
| 工程与混音 | storage.py 保存版本化 JSON、相对路径和旧版本。studio_session.py 管理片段引用、采样级时间点、音量包络与混音。studio_timeline.py 和 studio.py 提供专业工作台 |
| 本机与发布 | hardware.py 查询系统、磁盘、驱动与设备。packaging 和 scripts 生成冻结程序、便携档案及 Inno Setup 安装器 |

## 0.4.0 共享模块和三个路由

- `intelligence.measure(samples, sr, cancel)` 统一旧测量栈；`inspect_file` 区分源格式和内部 PCM；`metrics` 为歌曲路径提供不运行音高检测的电平/频带测量。`routing` 始终允许人工选择，`unknown` 不会被阈值伪装成源分类。
- 独立人声沿用 `service.tuning_plan → engine.process`。歌曲路径由 `service.separate_project` 使用固定、校验过的本地模型，生成原始双轨，再由 `service.plan_song` 形成 `song` 参数。分离及整曲渲染都在临时目录成功后才发布原始分轨。
- `song.vocal_params` 生成人声保守链，`song.process_stems` 只作轨道增益/伴奏 EQ，**不另造混音器**。`studio_session.Session.render` 沿用现有编排、总线与保护。`song.master_mix` 在整条混音总线之后处理；有 `song` 的工程强制旁通人声层 `master`，避免二次母带。
- 会话同时持有 `sources`（原始分轨）、`tuned_vocal`（调音人声）、`mix_sources`（增益/EQ 后送入 Studio 的两轨）、`output`（最终母带）。进入工作室使用 `mix_sources`，不能退回原伴奏或重复应用歌曲增益。
- `.voxproj` 外层仍为 v1；新增 `mode`、`song`、`separation` 为可选字段。不含这些字段的旧工程仍执行原路径。原始媒体不写入工程文件；相对路径、重新定位、备份和撤销沿用既有机制。
- 各任务通过取消 Event 报告中断，内部采样数组检查时长/声道/有限性，失败不提交新 Session。新报告保留处理前两轨、母带前总线、母带后总线和实际 inference provider；编码文件需另行回读。

**边界：**歌曲建议目前使用全曲积分响度/频带，不宣称时间对齐的语义掩蔽检测。工作室已有同窗平衡与选频侧链，未来可将其证据接入建议层。DSP 与同一模型的重建守恒，不代表分离无串音或成品音质达标。

## 一次渲染

1. 仅打开原始音频进行读取。解码为 44,100 Hz、左右声道 float32 PCM，并另存原文件的采样率、位深和声道元数据。
2. 对原音测量，建立波形与信号报告。分离后的工程另测人声，避免把整个伴奏响度用作人声压缩器阈值。
3. 根据风格和测量形成参数。用户可改写数值、旁通、顺序与句尾发送位置。保存文件保留这些最终参数。
4. 从原始人声重渲染，按多轨编排列入伴奏、FX 及外部素材。最终缓冲经峰值检查、必要衰减与复测后才能提交到主窗口。取消或异常保留此前的结果。
5. 导出从完成的混音缓冲开始。编码器写入目标目录临时文件，成功后以禁止覆盖的方式发布。工程与预设使用原子 JSON 替换。

## 约束

0.1.1 的分析入口为 `service.measure`。它组合声学分析、`segments.analyze_segments` 的时间区间、`quality.quality_metrics` 的三秒响度与声道相关度，以及每类发声段的局部空间证据。`service.tuning_plan` 生成可保存的自动化列表。`reference.match_segments` 根据同类发声的测量差对既有控制量作有界调整，参考录音的采样不会加入渲染。

效果链按已有工程顺序执行。`engine.process` 可记录实际改变采样的环节、同一批安静窗的降噪变化、EQ 的前后频带功率及压缩器逐时间窗的峰值衰减。试听器可以读取一个模块的输入输出。应用服务检查混音时长、声道、有限值和母带电平，必要时统一衰减并复测。更换同一路径的录音、参考或分轨后，大小或修改时间发生变化即重新解码。

响度与真峰值针对单声道和立体声工作流，内部播放与处理采用双声道。可显示信号证据的估计仍有置信边界。没有训练语义识别器来判断口音、歌词重点或演唱者身份。当前发布的神经网络任务为双分轨分离，其他处理可以断网独立工作。跨设备重新打开工程会重新解码、混音与测量，素材变更可能改变结果。
