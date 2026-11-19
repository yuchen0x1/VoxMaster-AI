# 安全政策

请通过 [GitHub 私密漏洞报告](https://github.com/yuchen0x1/VoxMaster-AI/security/advisories/new) 提交漏洞。避免在公开 Issue 中附带利用细节、私人录音或凭据。

当前维护线为 0.3.x；历史版本不接收独立回补。网络仅用于用户主动请求的模型管理和软件更新。基础 DSP、工程与 CLI 在本地运行。第三方编解码与模型处理的是不可信文件，建议及时升级，不要以管理员权限运行工作站。

软件更新只信任内置 Ed25519 公钥签名的官方清单；清单约束版本、包名、URL、长度和 SHA-256，下载只接受本仓库 GitHub Releases 与其资产 CDN，执行前再次计算散列。自定义 HTTPS 清单保留为只读版本查询，不能授权安装。签名不等于 Windows Authenticode，也不构成模型或音频质量的保证。

更新私钥不在仓库，存入 GitHub release 环境 Secret。不得将私钥用于客户端。若泄露，停止发布更新、撤销 Secret，并通过独立可信渠道重新分发含新公钥的客户端；不能用已失守的旧密钥为轮换背书。

自动化默认只读权限；发布任务单独获得 `contents:write`，每周分支治理任务另需 `contents:write` 与 `issues:write`，仅在 D 类分支（已完全包含于 main、无开放 PR、超过宽限期）上执行删除，并在删除前重新检查开放 PR。所有外部 Action 固定到完整提交，Dependabot 负责提醒升级。安全与依赖扫描结果以 Actions 实际结果为准。
