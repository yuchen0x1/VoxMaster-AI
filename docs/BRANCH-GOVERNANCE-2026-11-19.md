# Git 分支治理审计报告（2026-11-19）

## 审计范围与方法

本次仅审计 Git 分支与远程仓库治理，不改变业务代码、平台架构或产品规划。执行了本地 `git status`、`git branch -a -vv`、`git fetch --prune origin`、远程跟踪引用核对，并通过 GitHub API 核对分支、Pull Request、保护状态和历史提交。

仓库：`yuchen0x1/VoxMaster-AI`

## 当前分支清单

| 范围 | 数量 | 分支 | HEAD | 最后提交 |
|---|---:|---|---|---|
| 本地分支 | 1 | `main` | `6100bfd` | `docs: record post-change regression baseline` |
| 远程分支 | 1 | `origin/main` | `6100bfd` | 与本地一致 |
| 远程默认分支 | 1 | `origin/HEAD → origin/main` | `6100bfd` | 稳定主分支 |

`git fetch --prune origin` 后没有发现已删除远程分支的残留跟踪引用。没有 `develop`、`feature/*`、`fix/*`、`hotfix/*`、`release/*` 或 Dependabot 活跃分支。

## A/B/C/D 分类

| 分类 | 数量 | 结论 |
|---|---:|---|
| A：可直接合并 | 0 | 没有非主分支；无待合并候选 |
| B：整理后合并 | 0 | 没有非主分支；无冲突处理任务 |
| C：暂时保留 | 0 | 没有仍在进行的远程分支 |
| D：可以清理 | 0 | 没有可删除的当前分支 |
| 受保护主分支 | 1 | `main` 不纳入 A/B/C/D 清理分类，作为稳定基线保留 |

### 分支差异、冲突和有效代码

当前只有 `main`，因此不存在跨分支提交差异、文件变更差异、冲突、重复实现或未合并有效代码。没有发现可以安全合并或删除的活动分支。

## 历史 Pull Request 与已消失分支

GitHub 历史记录仍保留已关闭 PR，但其源分支不再是当前远程分支：

- [PR #11](https://github.com/yuchen0x1/VoxMaster-AI/pull/11)：`chore/actions-major-bumps`，已合并，源分支已不在远程分支清单中。
- [PR #6](https://github.com/yuchen0x1/VoxMaster-AI/pull/6)：`dependabot/pip/onnxruntime-1.32.0`，已关闭未合并，源分支不在当前远程分支清单中；依赖升级受平台兼容性约束，不能自动重开或合并。
- [PR #7](https://github.com/yuchen0x1/VoxMaster-AI/pull/7)：`dependabot/pip/scipy-1.18.1`，已关闭未合并，源分支不在当前远程分支清单中；Python 3.11 基线不满足该升级条件。
- [PR #8](https://github.com/yuchen0x1/VoxMaster-AI/pull/8)：`dependabot/pip/numpy-2.5.5`，已关闭未合并，源分支不在当前远程分支清单中；目标版本需要更高 Python 基线。
- [PR #9](https://github.com/yuchen0x1/VoxMaster-AI/pull/9)：`build(deps): bump av`，已关闭未合并，源分支不在当前远程分支清单中；PyAV 发布编解码库替换链尚未完成整链验证。
- [PR #10](https://github.com/yuchen0x1/VoxMaster-AI/pull/10)：`build(deps): bump mpmath`，已关闭未合并，源分支不在当前远程分支清单中；当前锁定版本与 Python/依赖基线保持一致。

这些 PR 的提交历史仍可追溯，未执行历史重写或强制删除。

## 无分支引用对象核查

`git fsck --full --no-reflogs --unreachable` 发现若干无引用提交，但它们均是已关闭 Dependabot/Actions PR 的旧提交，不是当前活动分支：

- `62e4832`：numpy 2.5.5；对应已关闭 PR #8。
- `7479bcca`：scipy 1.18.1；对应已关闭 PR #7。
- `b89af5b`：mpmath 1.4.1；对应已关闭 PR #10。
- `c050f5f`、`25f9c0c`、`4ded1c8`、`bf9b298`：Actions major bump 的中间 PR 提交，已由 PR #11 整理合并，当前 `main` 已包含最终结果。

- 无引用 tag `04dd21e` 是旧的 annotated `v0.3.0` 标签对象，指向修复前的 `fdc8243`；当前正式 `v0.3.0` 直接指向修复后的 `4794d57`，当前 `v0.3.1` 指向 `51a4ffc`。标签对象不属于分支清理范围，本次保留。

这些对象仍可能被 GitHub PR 历史或本地对象库回收策略保留；本次不执行 `git gc`、对象删除或历史重写。它们没有可删除的分支引用，也不构成 C 类活动分支。

## 合并与清理执行结果

- 实际合并：**0 个**。没有满足条件的非主分支。
- 实际删除远程分支：**0 个**。没有安全可删除的当前远程分支。
- 实际删除本地分支：**0 个**。本地只有 `main`。
- 冲突修复：**0 项**。没有待合并分支。
- 强制推送：**未执行**。
- 主分支历史重写：**未执行**。

尝试运行仓库内只读治理脚本时，GitHub API 返回匿名请求 `HTTP 403 rate limit exceeded`，因此没有把该次脚本失败伪装成成功；分支结论由本地 `git fetch --prune` 与 GitHub 分支 API 交叉核对得出。带认证 token 的下一次定时工作流可正常执行完整 API 扫描。

## 主分支保护与权限

GitHub 分支列表 API 将 `main` 标记为 `protected: true`。详细 protection API 在当前匿名查询下返回 `401 Requires authentication`，因此无法独立确认 required checks、管理员绕过、过期审批等细节。

本次仓库同步过程中远端曾返回“Bypassed rule violations for refs/heads/main”，并列出“Changes must be made through a pull request”和“4 of 4 required status checks are expected”。这说明当前凭据具备直接推送绕过保护规则的权限。后续建议：

1. 禁止普通维护流程直接推送 `main`；
2. 要求 Pull Request 和四项必需 CI 检查；
3. 仅允许发布环境或紧急维护者使用明确审批的绕过权限；
4. 使用已认证 API 复核 required status checks、管理员 bypass、线性历史和 force-push 禁止项。

## 长期治理机制

仓库已有 [分支治理工作流](../.github/workflows/branches.yml) 和 [分支治理脚本](../scripts/branch_governance.py)：

- 每周定时或手动运行；
- 分页读取全部远程分支和开放 PR；
- 将分支按与 `main` 的关系分类；
- 只有完全包含于 `main`、无开放 PR、超过宽限期的 D 类分支才允许清理；
- 删除前重新检查开放 PR，API 异常按安全路径保留；
- B/C 类分支只报告，不自动合并或删除；
- 自动生成 Markdown/JSON 报告，并对需要人工决定的分支创建或评论治理 Issue。

工作流会在运行前幂等创建 `branch-governance` 标签。当前 API 标签列表在本次扫描时尚未显示该标签，但当前没有 flagged 分支，因此没有触发告警路径；下一次带认证的工作流运行会负责创建它。

## 验证结果

- 本地分支审计：完成，`main` 与 `origin/main` 同步。
- 最新本地测试基线：`128 passed, 2 skipped`。
- GitHub CI：运行 [44437468308](https://github.com/yuchen0x1/VoxMaster-AI/actions/runs/44437468308) 针对当前 `main` 提交成功。
- 当前发布版本：v0.3.1；发布资产与标签保留，不删除历史标签。
- 工作区：除本报告这一份新增未跟踪交付文件外，未修改已跟踪文件；未执行任何业务代码改动。

## 最终结论

当前仓库已经是“单一受保护主分支、无活动开发分支、无待合并分支、无可安全清理分支”的状态。按照安全边界，本次不执行任何合并或删除；无动作本身是审计结论，而不是遗漏。后续新分支应通过 Pull Request 和 CI 后再进入 `main`，废弃分支由治理工作流在确认 D 类后清理。
