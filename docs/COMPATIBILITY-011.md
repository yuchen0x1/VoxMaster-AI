# 0.1.1 Windows、音频设备与推理后端验收

2026-11-18，Windows 11 Pro x64 10.0.26300，AMD Ryzen 9 8945HX（16 核、32 线程），79.2 GiB 物理内存，AMD Radeon 610M 与 NVIDIA RTX 5060 Laptop GPU，NVIDIA 驱动 610.62、专用显存 8,151 MiB。以下是源码运行环境验收。安装和便携版的验证另见[打包说明](PACKAGING.md)。

## 系统、显示和监听

| 项目 | 状态 | 证据与范围 |
|---|---|---|
| Windows 11 x64 | PASS | 在原生 Qt Windows 平台创建主窗口、打开录音、调音、输出并恢复工程。 |
| Windows 10 x64 | BLOCKED | 当前账号调用 Hyper-V Get-VM 被拒绝。常见路径没有可用的 VirtualBox 或 VMware 来宾环境。Qt 6.12 的上游 Windows 10 x64 支持下限是 1809，本产品在真实 Win10 上的完整安装及闭环仍待验证。[Qt 官方矩阵](https://doc.qt.io/qt-6/windows.html) |
| 高 DPI | PASS | 同一台 2560×1600 面板、Windows 原生 125% 缩放。分别启动 4 个 Windows Qt 进程，以进程级缩放得到 DPR 1.0、1.25、1.5、2.0。逐一在可用工作区内布局、抓取主窗，断言波形、一键调音、播放及导出控件均在视口。200% 的抓图为 2560×1460 像素。[100%](evidence-011/dpi-0.8.json) · [125%](evidence-011/dpi-1.json) · [150%](evidence-011/dpi-1.2.json) · [200%](evidence-011/dpi-1.6.json) |
| 跨显示器混合 DPI | PARTIAL | Qt 原生屏幕枚举及 WMI 均报告一个活动显示器。另建 Qt Offscreen 双屏模拟，将同一主窗移至 150% 副屏再移回 100% 主屏，抓图 DPR 顺次为 1、1.5、1。初次仅设置平台设备 DPR 时副屏快照仍为 1，改为按名称配置 Qt 屏幕缩放后通过。窗口跨实体屏移动和不同刷新率仍待双屏实测。[模拟初测](evidence-011/virtual-screens.json) · [模拟复测](evidence-011/virtual-screens-final.json) |
| 切换输出 | PASS | 在 Senary 板载输出的 MME、DirectSound、WASAPI 端点间实切 18 次。切换时保持循环区间和播放指针，18 次输出检查均未欠载。新打开的 WASAPI 共享流允许 Windows 转换设备采样率。[路由记录](evidence-011/route.json) |
| 耳机断连与再次连接 | PARTIAL | 第一轮连续试听停止，随后新的设备枚举中 OnePlus 蓝牙端点已消失。此事件的具体触发动作没有记录。修复后注入端点失效，验证回退 Windows 默认输出、保留循环及游标、默认输出持续失败时结束重试。设置中的「刷新设备」会在所有试听停止时重新枚举端点。未完成有人在场的物理拔出、插回和试听。 |

## 两种 GPU 后端分别验证

两次均使用 Spleeter 固定版本的两份 SHA-256 验证权重。输入是 8 秒 FLEURS 真人普通话叠加已知伴奏，双声道 352,800 帧。每次先跑 CPU 作为数值对照，再执行所选 GPU。验收要求两个 ONNX 图各自留下所选执行提供程序的算子记录、最终一块实报该提供程序、分轨重建误差低于 10⁻⁶、人声 SDR 对相同输入提高超过 3 dB。

| 后端 | 状态 | 8 秒分离用时 | 进程显存使用 / DXGI 预算 | 与 CPU 最大采样差 | 双轨重建最大误差 | 人声 SDR 提升 |
|---|---|---:|---:|---:|---:|---:|
| 发行依赖 DirectML 1.24.4 | PASS | 2.377 s | 567 / 7,131 MiB | 2.38×10⁻⁷ | 1.49×10⁻⁸ | 10.37 dB |
| 独立源码环境 CUDA EP 1.24.4 | PASS | 2.954 s | 398 / 7,131 MiB | 8.42×10⁻⁶ | 1.49×10⁻⁸ | 10.37 dB |

机器上仅安装了 NVIDIA 显示驱动，额外 CUDA 测试依赖下载至工程临时虚拟环境，使用 NVIDIA CUDA runtime 12.9.79、cuBLAS 12.9.2.10、cuDNN 9.28.1.4。显存读数取自计算完一块后的进程快照，瞬时峰值可能更高。CUDA 通过驱动提供的 LUID 定位对应 DXGI 适配器。标准 Windows 发行依赖仍为 DirectML。两种测试的完整模型与硬件证据见 [DirectML 日志](evidence-011/directml-final.jsonl)和 [CUDA 日志](evidence-011/cuda-heuristic.jsonl)。

第一次 CUDA 卷积触发 cuDNN 的延迟加载，依赖文件存在但加载器没有找到 tensor-IR 插件，子进程转由 CPU 完成。早期测试按消息前缀判断后端，曾把包含 CUDA 名称的回退消息错判为成功。修正脚本后，复现记录正确报 FAIL。推理子进程现在加载已安装的 cuDNN 插件目录，并由应用统一管理 CPU 重试。调整卷积方案搜索后，另一次 8 秒推理从 58.131 秒降至 2.954 秒。不同轮次可能受到缓存及并发负载影响。cuDNN 在方案选择阶段曾输出候选图不支持警告，最终图执行与数值断言均通过。[复现失败](evidence-011/cuda-before-fix.jsonl) · [初次修复结果](evidence-011/cuda-final.jsonl) · [ORT CUDA 官方配置](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)

## 故障与恢复

- PASS · 中止实际执行完第一块的 DirectML 专属推理进程，父进程在下一块使用 CPU 重算，返回全时长结果。执行了 tests/test_models.py 中的 test_recover_active_gpu_worker_exit。真实显存耗尽留待受控显卡环境核验。
- PASS · 在真实模型副本内翻转一个字节，离线校验识别同长度损坏。重新复制原文件后恢复通过。在一次真实 DirectML 任务完成第一块时取消，0.453 秒后退出，活动子进程数归零，可重新取得模型锁。同机 CPU DSP 调音在发起后 0.062 秒因取消退出。[故障验收](evidence-011/model-faults.json)
- PASS · 独立 Qt 测试进程导入真人录音，点击一键调音并产生自动保存，再由 Windows 强制结束该测试进程。将录音文件移位后，读取恢复工程、重新定位录音，冷重建的浮点输出与崩溃前 SHA-256 一致。旧测试使用 CRT 的立即退出，Windows DLL 卸载阶段曾触发 PySide 访问异常，现改用本进程的 TerminateProcess 直接模拟强杀，连续三次验收通过。[恢复测试](../tests/test_compatibility_011.py)
- PARTIAL · 注入 4 KiB 可用空间，WAV 编码在创建临时文件前提示不足；另在导出提交、工程刷盘时注入 ENOSPC，验证导出没有残留、原始录音和上次工程完好。未在用户系统盘制造空间耗尽，也未覆盖所有文件系统的真实配额行为。

## 复现

在项目根目录执行，日志文件需为新文件名，weights 指向包含两份已校验 ONNX 权重的本地目录。

```powershell
$weights = Join-Path $env:LOCALAPPDATA 'VoxMasterAI/models/spleeter-2stems-7001ba31'
.\.venv\Scripts\python.exe scripts/probe_accelerator.py DirectML $weights build/probe-directml.jsonl
.\.venv\Scripts\python.exe scripts/probe_model_faults.py $weights build/probe-model-faults.json
uv venv --python .venv/Scripts/python.exe build/qa-cuda
uv pip install --python build/qa-cuda/Scripts/python.exe 'onnxruntime-gpu[cuda,cudnn]==1.24.4' 'nvidia-cudnn-cu12==9.28.1.4' 'pyside6-essentials==6.12.0' 'av==18.1.0' 'numpy==2.4.6' 'scipy==1.17.1'
.\build\qa-cuda\Scripts\python.exe scripts/probe_accelerator.py CUDA $weights build/probe-cuda.jsonl
.\.venv\Scripts\python.exe scripts/probe_host.py route build/probe-routing.json
.\.venv\Scripts\python.exe scripts/probe_host.py virtual-screens build/probe-dual-screen.json
foreach ($scale in '0.8','1','1.2','1.6') {
    $env:QT_SCALE_FACTOR = $scale
    .\.venv\Scripts\python.exe scripts/probe_host.py dpi "build/probe-dpi-$scale.json"
}
Remove-Item Env:QT_SCALE_FACTOR
```
