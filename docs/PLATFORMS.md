# 平台可行性与支持边界（2026-11-18）

核心是本地离线分析、调音、非破坏工程、人声分离与专业监听，依赖 NumPy/SciPy、PyAV、PortAudio、Qt Widgets 和 ONNX Runtime。既有 DSP 与工程不替换。没有服务端、数据库账户或公共上传 API。

| 平台 | 结论 | 核心、体验和权限 | 成本、分发与更新 |
|---|---|---|---|
| Windows 11 x64 | A | 原有原生 Qt 窗口、键盘/拖放、多轨和本机音频；DirectML/CPU | 主要交付；Inno 用户级安装、ZIP；签名清单更新，Authenticode 待证书 |
| Windows 10 x64 | A，待实机验收 | 需满足 Qt、Python 与运行库最低系统；不能将 Inno 的最低版本当作完整兼容证据 | 共用构建；无来宾设备，仍需实测，不宣称通过 |
| Linux 通用 x64 | B | 原生 Qt 桌面和 CLI；CPU 分离；PortAudio、字体、显示服务器由系统提供 | 本轮进入源码适配与 CI；二进制格式须按发行版验收后推广 |
| Ubuntu 24.04 | B | CI 覆盖无屏 Qt、DSP、工程及 CLI；实体监听待测 | 源码环境升级；尚无已验收 DEB/AppImage |
| Debian | B，待验收 | glibc、Qt wheel 与 PortAudio 版本需核查 | 共用 Linux 源码路径；不标记通过 |
| Fedora | B，待验收 | PipeWire/ALSA 与 Qt 插件需发行版验证 | RPM 不发布，避免假支持 |
| Arch Linux | B，待验收 | 滚动依赖与系统音频变化需持续回归 | 源码路径；不承担未测二进制兼容 |
| macOS Intel | B | 原生 Qt 样式、系统字体、Application Support、CPU Runtime；CI 独立 Intel runner | 源码试验支持；DMG、Keychain、签名公证需 Developer ID 与实机 |
| macOS Apple Silicon | B | ARM64 原生 Python/Qt 与 CPU 模型；不借 Rosetta 冒充 ARM 验收 | 独立 ARM runner；源码试验支持，设备监听待测 |
| Android 手机 | C | SciPy/PyAV/ONNX 的移动编译、后台限制和触控编辑需重新产品化 | 高开发/维护成本；APK 和系统安装更新未开发 |
| Android 平板 | C | 大屏有编辑价值，但音频路由、触控时间轴与存储授权缺专用实现 | 与 Android 基础能力共同延期 |
| 折叠屏 | C | 重布局、姿态和生命周期需真机验证 | 无移动端基础，不单列假支持 |
| iOS | C | Python/Qt/模型栈不具备现成完整分发链，沙盒与后台音频需独立实现 | App Store、证书、真机与团队资源不足 |
| iPadOS | C | 多轨触控有价值，需文件提供程序、音频会话和专门手势 | 随 iOS 原生产品评估；不做网页套壳 |
| 桌面 Web | C | 本地 Python DSP 不在浏览器运行；服务端方案会改变离线隐私和运维模型 | 需要 API、任务队列、上传安全与数据库，未引入新基础设施 |
| 移动/响应式 Web | C | 资源限制、文件沙盒、实时监听和长录音后台受限 | 须先完成 Web 引擎与触控设计 |
| PWA | C | 离线缓存不能替代 Python 音频与模型运行时 | 未做 Web，因此不添加空 Service Worker |
| Chrome 扩展 | D | 扩展权限不适合完整本地 DAW 与大模型，不能完整保留核心 | 无足够价值；不开发 |
| Edge 扩展 | D | 同 Chromium 限制 | 不开发 |
| Firefox 扩展 | D | 同时增加 WebExtension 与本地宿主维护，核心仍需另装 | 不开发 |
| CLI | A | 同一测量/渲染服务，JSON 输出，多文件串行，失败继续且退出非零，禁止覆盖 | 本轮开发；源码/Windows EXE 均有入口；随统一版本更新 |
| Docker | C | 离线批处理可用，但 GUI/音频设备传递复杂 | 当前无隔离批量服务需求，避免额外镜像维护 |
| NAS | C | 可通过 CLI 执行，部分 ARM 设备不满足 wheel/内存条件 | 不宣称现成 NAS 应用 |
| 私有化部署 | C | 本地桌面已满足单用户隐私；多用户服务需独立安全模型 | 无用户认证和任务隔离服务，未建设 |
| 云服务器 | C | 无显示环境可使用源码 CLI；音频服务是不同产品 | 无公网 API，不部署演示上传服务 |

依据：[Qt 平台矩阵](https://doc.qt.io/qtforpython-6/overviews/qtdoc-supported-platforms.html)、[DirectML 限制](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html)、[GitHub 原生 runner 架构](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。A/B 表示投资决定，不等于已构建/已验证/已发布。各阶段状态见 [交付记录](DELIVERY-020.md)。

## 本轮功能矩阵

| 功能 | Windows | Linux 源码 | macOS 源码 |
|---|---|---|---|
| 离线 DSP、工程和多轨 | 保留，回归验证 | 同一核心，CI 验证中 | 同一核心，独立双架构 CI 验证中 |
| 系统目录/字体/默认设备文案 | 原有目录保持 | XDG、Linux 字体 | Application Support、PingFang/系统样式 |
| 分离加速 | DirectML/CPU | CPU；GPU 仅按独立环境验证 | CPU；不宣称 CoreML |
| CLI 分析/批量调音 | 有 | 有 | 有 |
| 安装包 | EXE / ZIP | 尚未交付 | 尚未交付 |
| 更新 | 官方签名下载→交互安装 | 源码环境升级 | 源码环境升级 |
| 回滚 | 重新安装保留的旧包；自动回滚未实现 | 保留旧环境，切回旧版本 | 保留旧环境，切回旧版本 |

Linux/macOS 原先若曾手动使用 `~/VoxMasterAI`，不要自动覆盖；复制确认后的设置到新目录或设置 VOXMASTER_DATA 指回原目录。Windows 数据目录、工程 schema=1、相对素材路径不变。全平台使用同一版本来源，新增功能必须在上述矩阵记录影响。
