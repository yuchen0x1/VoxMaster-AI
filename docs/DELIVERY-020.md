# VoxMaster AI 0.2.0 交付记录

日期：2026-11-18（Asia/Shanghai）  
分支：`codex/ecosystem-0.2`  远程：`git@github.com:yuchen0x1/VoxMaster-AI.git`

## 已完成

| 项目 | 状态 | 证据 |
|---|---|---|
| 原项目目录、模块、依赖、测试、构建、GitHub 现状审计 | PASS | [AUDIT-020](AUDIT-020.md) |
| 32→37 个相关项目的 GitHub 结构/源码/提交/Issue/Release 调研 | PASS | [RESEARCH-020](RESEARCH-020.md)、[upstreams.json](evidence-020/upstreams.json)；34 个源码入口成功读取 |
| 36 项升级候选，实施/延期/阻塞决定 | PASS | RESEARCH-020 |
| Linux/macOS 用户目录、字体和条件依赖适配 | PASS（静态/CI 已准备） | [PLATFORMS](PLATFORMS.md) |
| 离线 CLI 分析和批量调音 | PASS | `app.py --cli analyze/tune`；真实 FLEURS 录音输出 JSON 和 WAV，重复目标以非零码拒绝 |
| 官方更新清单、Ed25519、来源限制、下载限额、SHA-256、安装前复核 | PASS（单测） | `tests/test_ecosystem.py` 16 passed；[UPDATING](UPDATING.md) |
| GitHub CI/Security/Release/每月上游扫描、Dependabot、Issue/PR 模板 | PASS（配置已提交本地） | `.github/` |
| GitHub release 环境、签名 Secret、main 保护 | PASS（远程 API 已返回成功） | 需要四个 CI 检查、禁止强推/删除、会话解决 |
| 真实桌面导入和一键调音 | PASS | [workstation.png](evidence-020/workstation.png)、[ui.json](evidence-020/ui.json)；原音 -42.22 LUFS，成品 -17.09 LUFS |
| 发布前逆向暴露面静态扫描 | PASS | [exposure-source.md](evidence-020/exposure-source.md)：185 文件、0 原生二进制、0 JS 产物，未发现静态严重/高/中/低项 |
| 版本一致性、compileall、Ruff F 检查 | PASS | `scripts/version.py` 输出 0.2.0；Ruff All checks passed |
| Windows 冻结、包自检、Portable/Source/安装器 | PASS | `scripts/build.ps1 -Phase Freeze/Package`；包自检运行时状态 PASS；`dist/` 生成四项发布产物 |
| 本地签名发布清单 | PASS | `dist/release/update.json`、`.sig` 与 SHA-256 逐项复核通过 |

## 测试与构建状态

- 原有未修改基线：103 passed、2 skipped，外层退出码 1；跳过项是未指定权重的神经网络测试，不能标记完整 PASS。
- 指定本机 ONNX 权重后，全量回归：121 passed；此前一次 120 passed/1 failed 的崩溃恢复超时在隔离复现和单独用例运行中均未重现，最新全量结果为 PASS。该用例仍保留 75 秒保护性超时，后续 CI 仍需观察资源竞争。
- 新增更新/平台/CLI 测试：16 passed；独立 CLI 真实录音分析与调音 PASS，第二次同名输出返回 1 且保留原文件。
- UI 原生截图脚本退出 0；实际窗口和更新窗口截图已保存。UI 截图只证明当前 Windows Qt 进程可渲染，不证明其他系统的视觉验收。
- Windows Freeze/Package：完整 FFmpeg/LAME 编解码构建、PyInstaller 双入口、包自检、Portable zip、Source zip、Inno Setup 安装器和 SHA256 清单均已完成；冻结包自检记录 `status: PASS`，CLI 冻结程序 `--version` 与真实录音分析通过。
- 本地发布清单已使用外部 Ed25519 私钥生成并用仓库内公钥验签；私钥未进入工作区或 Git 历史。

## GitHub 与发布边界

工作区尚未提交、推送、打标签或创建 0.2.0 Release，因此没有伪造 Release 地址或下载资产。远程已有 v0.1.1 保留不覆盖。完成 0.2.0 发布还需：

1. 提交当前分支并推送，等待四个 runner CI 与 Security 工作流完成。
2. 在真实 Windows 环境完成安装/卸载验收；补 Authenticode 证书后再改变签名说明。
3. 由 release environment 注入签名 Secret，重新生成并复核 `update.json` / `.sig`。
4. 合并 main、打 `v0.2.0` 标签，由 Release 工作流创建草稿并上传资产；发布后检查每个资产的长度、散列和签名清单。

未开发 Android/iOS/Web/PWA/浏览器扩展、Docker/NAS 服务；原因和后续条件见 PLATFORMS。Linux/macOS 只有源码和 CI 试验支持，没有安装包或系统级自动更新。Windows 更新没有自动回滚和启动健康检查；请按 UPDATING 保存旧包与工程。
