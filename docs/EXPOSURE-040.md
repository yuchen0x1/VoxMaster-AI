# 0.4.0 发布产物暴露面审计

## 1. 总览

对象：本轮隔离构建的 `dist/VoxMasterAI/VoxMasterAI.exe`（Windows x64，PyInstaller **onedir** 冻结）。使用 `reverse-engineering-exposure-audit` 的 `exposure_scan.py`，初次结果 `.audit/040-post/exposure-native-initial.json`；最终冻结产物以该基线复测，结果 `.audit/040-release-review/exposure-shipped.json`。复测仍为 **83 / C**，`PE-SIGN`、`PACK-PYI` 保持不变，无新增、无加重、无已修复项。源码改动修复了音频事务与数据保护，但没有使未签名或容器可提取问题消失。交付状态见 [DELIVERY-040.md](DELIVERY-040.md)。

原生单 EXE 启发式扫描为 **83 / C**，评分仅作问题排序，不是安全认证。目录按 package 画像扫描跳过了 241 个原生二进制，因此该画像的“无发现”不能解释为“安全”。本报告以单 EXE 的 native 画像为准；未审计每个第三方 DLL。

## 2. 发现清单

| 编号 | 严重度 | 发现 | 命中 | 能利用的信息 |
|---|---|---|---:|---|
| PE-SIGN | 高 | 无 Authenticode 签名证书目录 | 1 | 无法由 Windows 发布者签名认证安装文件来源 |
| PACK-PYI | 中（本项目接受） | PyInstaller 容器带 MEI 魔数，Python 字节码可提取 | 1 | 可以读取与修改客户端代码；MIT 开源项目不把算法保密作为安全边界 |

## 3. 证据与处置

- `PE-SIGN`：PE `DataDirectory[SECURITY]` 为空。项目没有提供代码签名证书，本轮不购买证书、不改变用户凭据。发布说明与 README 保留“未签名”，正式公发前由发行人选择可信证书并使用 `signtool sign /fd SHA256 /tr <可信时间戳服务> /td SHA256 ...` 后再次验证签名和哈希。应用的 Ed25519 **更新清单**不能替代 Windows Authenticode 签名。
- `PACK-PYI`：扫描器将其通用描述为“单文件包”，实际构建为 onedir（双 EXE + `_internal`）。两者均带可读 Python 代码；这是容器格式证据，不是秘密泄漏。项目已经按 MIT 发布源码，增加混淆、加壳或迁云不会带来相称收益，也违反本地优先产品方向，因此不做此类改变。
- 扫描未证明无密钥、无注入或运行时安全；这些需源码与运行时审查。此次没有新增凭据、账户、遥测或音频上传。

## 4. 客户端无法解决的问题

任何随本地程序下发的算法和模型权重都可被有权限的本机用户取得。不能用客户端加密承诺保密；本项目选择开放源代码与本地处理，不把算法隐藏/许可开关作为授权边界。模型代码、权重、数据与 SDK 许可仍分开处理，见 [THIRD_PARTY.md](THIRD_PARTY.md) 与 [RESEARCH-040.md](RESEARCH-040.md)。

## 5. 修复顺序与发布门禁

1. **P0**：不打包私有音频、缓存模型或凭据；本轮新增源码归档过滤器和固定 FLEURS 哈希白名单测试。
2. **P1**：发行人提供签名能力后签署 EXE/安装器并复核；当前保留未签名限制，不将包标为已完成生产签名。
3. **P2**：持续更新原生编解码/推理依赖、逐版本保留对应源码与许可证。扫描未覆盖的 DLL 与实体 Windows 10 兼容由后续发行验收完成。