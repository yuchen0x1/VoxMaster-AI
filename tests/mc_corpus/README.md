# 喊麦听审素材库

sources.json 用稳定编号记录输入文件的来源、类型依据、授权范围、制作者、哈希和渲染预设。线上素材取自 [VocalSet 1.1](https://zenodo.org/records/1203819) 和各 Freesound 作品页。Freesound 输入采用发布页公开的 HQ MP3 预览，制作人的设备说明对应原始录音。FLEURS 和 VocalSet 为 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，列出的 Freesound 录音选用 [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)。VocalSet 作者为 Julia Wilkins、Prem Seetharaman、Alison Wahl 和 Bryan Pardo。各样本音频不会随程序分发，公开样本的获取方式如下。

## 重建

准备正式 0.1.0 源码包，将其放在 build/acceptance-011/baseline-010-source.zip，脚本会校验已发布的 SHA-256。用户提供的五首歌保存在本机授权目录中。公开清单的 local 项只标记 `private_digest_required=true`，不公开私有 SHA-256；原指纹映射保存在被 `.gitignore` 忽略的 `.audit/040-release-review/private-corpus-digests.json`，格式为 JSON 对象 `{ "MC01": "<64 位十六进制 SHA-256>", ... }`，不得提交或分发。渲染 local 项必须显式传入 `--private-digests`；缺失条目、非法指纹或输入不匹配都会拒绝执行，不会跳过校验或自动重算指纹基准。仅选公共素材时可省略该参数，仍校验清单中的原哈希。生成文件进入 build/acceptance-011，保留输入与各版本原文件，录音、盲听 WAV 和密钥仅本机可见。

```powershell
$qaRoot = 'build/acceptance-011'
$py = '.venv/Scripts/python.exe'
& $py tests/mc_corpus/fetch_vocalset.py "$qaRoot/external"
& $py tests/mc_corpus/fetch_freesound.py "$qaRoot/external"
& $py tests/mc_corpus/mix_controls.py "$qaRoot/external"
& $py tests/mc_corpus/render_trials.py 0.1.0 --local "$env:USERPROFILE/Desktop/yin" --private-digests '.audit/040-release-review/private-corpus-digests.json'
& $py tests/mc_corpus/render_trials.py 0.1.1 --local "$env:USERPROFILE/Desktop/yin" --private-digests '.audit/040-release-review/private-corpus-digests.json'
& $py tests/mc_corpus/blind_trials.py
```

0.1.0 从校验过的发布源码 ZIP 导入模块，执行该版本窗口生成参数的原方法。0.1.1 从当前工程导入 service.tuning_plan。两个版本都完整分析、处理、复测同一输入，随后使用相同的采样位置截取片段。工程证据位于 engineering/版本/素材编号/report.json，包含设置、分析、复测、处理时间、操作系统及音频时间范围。--only 可对指定素材工作。--resume 仅用于相同引擎版本的中断续跑，代码变化后应使用新的输出目录或归档旧结果。

每份盲听文件为 44.1 kHz 双声道 24-bit PCM，仅施加恒定增益。FFmpeg ebur128 在导出后独立回读各文件，要求匹配目标误差 ≤0.10 LU 且真峰值 ≤−1 dBTP。每组六种版本顺序构成一个平衡区组，区组内随机。每次创建新的盲听目录可获得新的顺序；监听者将答案写入其个人表。参见 [音频报告](../../docs/AUDIO-011.md) 和 [听审说明](../../docs/LISTENING-011.md)。

## 受控重混

RM01 取 FS738227 的第 17–29 秒，与 FS353853 实体架子鼓循环混合，鼓对人声 RMS 为 +6 dB。RM02 使用相同录音，与真实远距人群 FS360702 混合，环境对人声 RMS 为 −9 dB。两者对同组源施加一致的输出峰值缩放。其目标比分轨可复核。它们描述后期构造的场景，不能代表近远场同一表演的同时录音。
