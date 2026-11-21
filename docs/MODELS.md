# 人声分离与模型中心

从模型中心下载 Spleeter 2-stem 后，可以离线将混音拆分为人声与伴奏。双轨与输入保持相同采样数。密集和声、强混响及与人声频带重叠的伴奏容易相互渗漏，建议用耳机独听两轨判断是否适合继续调音。

## 下载、暂停与迁移

首次下载约 75 MiB，安装包不含权重。在模型中心可以暂停、续传、取消、删除或重新下载。进度来自实际字节数。每个文件写入临时文件，长度和 SHA-256 均匹配后才成为可用权重。使用模型前再次检查两个文件。选择新的模型目录后，软件会逐个核对复制件，再切换设置并移除旧位置对应的权重。

“检查上游版本”只发送模型仓库标识。内置目录锁定经过验证的提交。若发布者有新版本，模型中心会显示新提交编号，软件版本更新后才启用对应权重。

任务运行时可以请求取消或关闭；窗口显示等待状态，待工作线程实际结束后关闭，不强杀线程，也不把已完成的文件操作声称为已撤销。取消或关闭后忽略迟到的进度和结果。上游检查分块读取，响应最大 1 MiB，设置 15 秒总时限检查和最多 3 秒的单次 socket 空闲等待；总时限或取消仍可能等待当前一次读取返回。DNS 解析及 HTTP 响应头解析不受该代码的硬性总时限保证，不能将“请求取消”等同于网络连接已经终止。

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| vocals.onnx | 39,318,336 | bdc16ab6bf6117ddd4842c19e80e40e2be188fc555295064d424616b0224ac97 |
| accompaniment.onnx | 39,318,343 | 671ace17acd3720674a2bc14de32ac6292453dec20d9eb0ba4255d4ad8e3d8c0 |

固定提交为 `7001ba316a615cacddb3f9ef3ec416661a277e26`。文件来自 sherpa-onnx 转换作者的公开仓库。Spleeter 源代码的许可证为 MIT，转换项目代码的许可证为 Apache-2.0。源作者尚未明确预训练权重的独立商业分发条款。[转换作者的模型仓库](https://huggingface.co/csukuangfj/sherpa-onnx-spleeter-2stems/tree/7001ba316a615cacddb3f9ef3ec416661a277e26) · [官方模型说明](https://k2-fsa.github.io/sherpa/onnx/source-separation/models.html) · [Spleeter 许可证](https://github.com/deezer/spleeter/blob/master/LICENSE) · [权重许可问题](https://github.com/deezer/spleeter/issues/959)

## 推理与频带

引擎以 44.1 kHz 立体声输入进行 4096 点短时傅里叶变换，帧移为 1024。每次输入固定 512 帧和 1024 个频率箱，前后预留 32 帧上下文。两个神经网络分别生成强度估计，软件按两者的能量比例提取人声，以混音减去人声得到伴奏。模型的有效带宽约 11 kHz，高于这一频率的成分留在伴奏中。[转换作者的张量接口与推理参考](https://github.com/k2-fsa/sherpa-onnx/blob/master/scripts/spleeter/separate_onnx.py)

CPU 可直接运行。Windows 发行版使用 ONNX Runtime DirectML 在兼容 GPU 上推理，从 DXGI 获取适配器编号、进程占用和显存预算。在双显卡机器上优先尝试专用显存较大的适配器。首块实际计算后，程序核对两张模型图的执行记录。加载、显存或算子执行出错时，会用 CPU 重新计算当前块。独立进程允许取消或回收异常退出的运行库。源码环境中若安装带 CUDA 提供程序的运行库，也可选择 CUDA。[ONNX Runtime DirectML 配置说明](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html)

## 本机验证

| 检查 | 结果 |
| --- | --- |
| 官方权重下载、暂停、续传与 SHA-256 | PASS。测试在 786,432 字节处暂停，从相同目录重新调用下载，两份最终散列均与固定清单一致。 |
| 真实普通话人声叠加已知合成伴奏 | PASS。截取 FLEURS 真人普通话样本前 8 秒。以原人声为真值，分离后人声 SDR 比原始混音提升 10.37 dB。此指标对应这一组测试素材。 |
| 本机已有喊麦录音 45–51 秒 | PASS。CPU 和 DirectML 均输出 264,600 帧，双轨重建最大样本误差 1.19×10⁻⁷，两种模式之间人声输出最大差值 1.97×10⁻⁶；此录音及其结果不随源码和软件提供。 |
| GPU 算子与资源监测 | PASS。实际执行适配器为 RTX 5060 Laptop，实测该进程专用显存 567 MiB，预算 7,131 MiB。相同音频在 CPU 模式的推理进程工作集约 504 MiB。 |
| 174.939 秒整曲 | PASS。两种模式均计算 17 块、每轨 7,714,816 帧。CPU 用时 4.98 秒，推理进程各块结束时工作集最高 532 MiB。DirectML 用时 3.47 秒，同一位置采样的工作集最高 334 MiB，显存均为 567 MiB。双轨重建绝对最大误差 1.19×10⁻⁷。计时包含模型校验与子进程启停，不含文件解码及导出。 |
| 跨块边界 | PASS。相邻模型块共享约 372 毫秒音频，用互补升余弦平滑过渡。整曲 16 个连接点的左右采样差绝对值最大为 0.4082，整曲相邻样本差的第 99 百分位为 0.5213。另用连续正弦检验恒等掩码的拼接与两端对齐。 |
| 模型中心控件 | PASS。在隔离的本机 HTTP 服务上实际点击下载、暂停、续传、重新下载、取消、校验、删除、迁移、手动 CPU 和重新打开窗口。取消首次下载会清除临时文件，取消重新下载则保留上次可用的完整模型。 |
| 运行中 GPU 进程意外退出 | PASS。测试主动终止处理完第一块音频的专属 DirectML 子进程，后续块经 CPU 恢复，完整轨道对照全程 CPU 的最大采样差小于 0.001，双轨重建误差小于 10⁻⁶。测试未制造物理显存耗尽。 |
| CUDA 运行库 | 0.1.0 分发使用 DirectML。0.1.1 已用独立 CUDA 12 / cuDNN 9 源码环境对两个 ONNX 图做算子级验证，在 RTX 5060 Laptop 分离八秒音频用时 2.954 秒。标准安装包继续提供 DirectML 与 CPU。[运行环境、故障复现与对照](COMPATIBILITY-011.md) |

在项目根目录运行以下命令可复现自动化测试。真实模型测试读取已经下载的本地 ONNX 文件。未设置路径时，对应测试会标为跳过。

```powershell
$env:VOX_MODEL_TEST_WEIGHTS = "$env:LOCALAPPDATA\VoxMasterAI\models\spleeter-2stems-7001ba31"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_models*.py" -v
$env:VOX_MODEL_TEST_MODE = "DirectML"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_models*.py" -v
```
