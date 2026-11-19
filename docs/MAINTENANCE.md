# 构建、发布和长期维护

## 发布规则

main 为稳定分支；功能分支经 PR 与四种原生 runner 回归后合并。产品版本从 vox/__init__.py 同步到 Inno 和 Windows 文件资源；标签必须匹配版本。0.x 仍为功能演进阶段，未验收的平台不能写入正式支持清单。

工作流：CI 执行版本、Ruff、编译、全量 pytest 和真实样本 CLI。Windows、Ubuntu、macOS ARM/Intel 使用各自 runner。Security 执行依赖漏洞扫描和 PR 依赖审查。Dependabot 每周提出依赖/Action 更新。Upstream research 每月生成只读调研工件，不自动改代码或发布。Release 仅标签触发：复用完整 CI→Windows 音频专用编解码构建→Qt 对应源码与通知→PyInstaller→捆绑包自检→Inno/ZIP/源码→统一资产名→签名更新清单→草稿上传→正式公开。

所有发布必须保留 Qt 对应源码、FFmpeg/LAME 来源及动态库通知。项目未新增开源许可，源码附件不等于授予复用授权。运行依赖与构建工具仍共用一个固定版本清单，后续可拆分，但须检查许可证通知收集范围。

本地构建 `./scripts/build.ps1`。签名 `python scripts/release_assets.py --key-file <工作区外私钥路径>`；不要在日志或命令行直接写私钥内容。正式发布将新版本提交到 main，随后 `git tag -a vX.Y.Z -m ...`、`git push origin vX.Y.Z`。标签工作流会先用 GitHub compare API 确认标签提交属于 main 历史，再创建 Release；标签工作流随后创建 Release。已有版本不可覆盖，失败修复用新版本标签，遗留草稿由维护者检查后处理，不自动删除。

## GitHub 设置与权限

发布任务使用 release environment，私钥仅通过 Secret 注入；默认 Actions 只读，发布任务单独 contents:write。外部 Action 固定完整 SHA。分支保护禁止强推、删除，要求 PR、最新基线的四个 CI 状态和解决讨论。小型单维护者项目不要求自我审查，必要时增加独立审查者和环境审批。

仓库权限、Secret Scanning、私密漏洞报告和保护规则是否已成功配置以 docs/DELIVERY-020.md 的实际 API 结果为准，不因文档存在就算成功。

分支治理任务是唯一另需 `contents:write` 与 `issues:write` 的定时例外；运行前幂等创建 `branch-governance` 标签，脚本分页读取分支/开放 PR，并在删除前二次检查开放 PR。
## 故障与发布后检查

构建、CI、签名失败时禁止公开正式版本。资产上传失败保留草稿，不用 clobber 覆盖已公开版本。发布后核对资产数量/文件名/下载长度，读取官方签名清单并完整下载验签后的安装器。正式安装、卸载、跨版本更新及失败回滚是独立验收，不由包自检替代。

后续每次变更更新平台功能矩阵、用户变更记录和测试证据。每月审阅上游工件，重大升级重新研究实现、许可证和安全变化。GitHub Issues 记录人工验收、实体设备差异和优先级，未经审查的上游新功能不能自动合入。
