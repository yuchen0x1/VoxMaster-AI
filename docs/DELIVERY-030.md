# VoxMaster AI 0.3.0 交付记录

日期：2026-11-19（Asia/Shanghai）
分支：`codex/ecosystem-0.2`  远程：`git@github.com:yuchen0x1/VoxMaster-AI.git`

## 已完成

| 项目 | 状态 | 证据 |
|---|---|---|
| 基线回归：119 passed / 2 skipped（跳过项为未提供本地权重的模型用例） | PASS | 本机 pytest |
| 工作流启动失败根因定位与修复：`${{ runner.temp }}` 在作业级 env 违反 GitHub 上下文规则，导致 0.2.0 推送后全部工作流无日志启动失败 | PASS | actionlint 检出；修复后新推送的 CI 正常排队并运行 |
| CI 新增 actionlint 工作流静态校验（固定 1.7.12 + 官方 SHA-256 校验） | PASS（本地 actionlint 0 告警；CI 任务待远端执行） | `.github/workflows/ci.yml` workflows 任务 |
| 上游调研刷新：37 仓基础信息 + 90 天提交活动（532 条提交，30 天活跃 21 仓） | PASS | [RESEARCH-030](RESEARCH-030.md)、[upstreams.json](evidence-030/upstreams.json)、[recent.json](evidence-030/recent.json) |
| 33 项升级候选清单与分级决定（实施 14、评估/已覆盖/暂缓/阻塞 19） | PASS | RESEARCH-030 |
| 本地会话健康检查（vox/health.py + app.py 集成；异常退出识别、版本感知提示、无遥测） | PASS | tests/test_health.py 5 项 |
| CLI `styles` 子命令与 `analyze/tune --report` 报告文件 | PASS | tests/test_ecosystem.py 17 项（新增真实子进程用例） |
| 更新窗口下载前展示安装包大小与 SHA-256 前缀 | PASS | vox/update_dialog.py；真实渲染截图 |
| Release 工作流发布后重读公开清单并逐资产验证（含 CDN 重试） | PASS（actionlint；远端执行待标签推送） | `.github/workflows/release.yml` |
| 月度维护扫描新增近 90 天上游活动（research_recent.py） | PASS（本地已产出 evidence-030/recent.json） | `scripts/research_recent.py` |
| 版本一致性 0.3.0（vox/__init__、Inno、version.txt） | PASS | `scripts/version.py` 输出 0.3.0 |
| 真实桌面 UI 验证：导入 FLEURS 真实录音 + 一键调音 + 官方更新窗口截图 | PASS | [ui.json](evidence-030/ui/ui.json)：原音 −42.22 LUFS → 成品 −17.09 LUFS；[workstation.png](evidence-030/ui/workstation.png)、[official-update.png](evidence-030/ui/official-update.png) |
| 全量回归（含新用例）：125 passed / 2 skipped | PASS | 本机 pytest；compileall 与 Ruff F 检查通过 |
| 提交与推送 codex/ecosystem-0.2 | PASS | e60f1f2..b868cb9 |

## 测试与验证状态

- 新增测试 6 项：健康标记生命周期/损坏容错/原子写入/版本感知提示/无标记关闭（5）+ CLI styles 与 report 真实子进程（1）。全部本地通过。
- 跳过的 2 项是未设置 `VOX_MODEL_TEST_WEIGHTS` 的神经网络分离用例，与 0.2.0 相同，不冒充完整。
- UI 验证仅证明当前 Windows 11 本机 Qt 进程可渲染与调音，不代表其他系统视觉验收。
- 工作流修复的真实远端证据：修复推送后 CI 运行名为 `CI`（此前显示文件路径）且进入 queued/running；release.yml 未再被分支 push 误触发。

## 发布边界（与 0.2.0 相同的诚实记录）

- Windows 安装器仍无 Authenticode 签名；无自动回滚。会话健康标记不能替代安装后专项验收。
- Linux/macOS 仍为源码与 CI 试验支持，无安装包。
- Android/iOS/Web/PWA/浏览器扩展/Docker/NAS 本轮仍未开发，理由见 [PLATFORMS](PLATFORMS.md) 与 RESEARCH-030 差距表。
- PyAV 18→19（GIL 释放修复）、模型镜像下载、自动回滚等候选保持暂缓，原因见 RESEARCH-030。

## 0.3.0 发布步骤（执行后回填）

1. 等待 CI 五项任务（4 平台回归 + workflows）全部通过 —— 见下方状态。
2. 合并 codex/ecosystem-0.2 → main 并推送。
3. 在 main 上打 `v0.3.0` 标签推送，由 Release 工作流创建 Release 并上传资产。
4. 运行 `scripts/verify_release.py` 复核公开清单、资产链接与 Ed25519 签名。
5. 回填实际 Release 地址与资产清单。
