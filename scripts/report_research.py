"""Convert recorded upstream evidence and explicit product decisions into a report."""
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSIGHTS = {
 'audacity/audacity': ('直接竞品', 'CMake 模块/测试边界；参考离线编辑与分析分离，不复制 GPL 界面/代码'),
 'Ardour/ardour': ('直接竞品', 'waf 构建与专业会话；参考非破坏编辑，避免引入复杂实时路由'),
 'LMMS/lmms': ('相邻竞品', 'CMake 与合成/编曲模块；完整 MIDI 编曲超出喊麦调音定位'),
 'musescore/MuseScore': ('相邻竞品', '大型桌面模块化与资源分层；谱面编辑不适用本轮'),
 'mixxxdj/mixxx': ('相邻竞品', '桌面构建/设备适配；参考设备身份和回归矩阵，不做 DJ 曲库'),
 'tenacityteam/tenacity': ('直接竞品', '桌面编辑器 CMake；参考可检查的文件编辑工作流'),
 'zrythm/zrythm': ('直接竞品', 'Qt/QML 与 CMake 演进，迁移不能只看旧版 Meson 文档；暂不迁移现有 Widgets'),
 'surge-synthesizer/surge': ('技术参考', '跨平台原生音频构建；合成器功能不直接吸收'),
 'Anjok07/ultimatevocalremovergui': ('直接竞品', '模型类型分支与分离调度；保留固定模型目录和可解释后端回退'),
 'facebookresearch/demucs': ('技术参考', 'apply_model 分块与重叠；仓库归档不等于不可参考，但不新增 Torch 打包负担'),
 'deezer/spleeter': ('直接竞品', 'separator 封装模型、音频适配器与会话；本项目继续使用单独下载 ONNX 权重'),
 'nomadkaraoke/python-audio-separator': ('直接竞品', '分离器门面与后端选择；模型授权仍须逐项审查'),
 'RVC-Project/Retrieval-based-Voice-Conversion-WebUI': ('相邻竞品', '实时 GUI 与推理边界；声线转换需另行授权及听审，延期'),
 'w-okada/voice-changer': ('相邻竞品', '服务端 VoiceChanger 管线；实时变声不是离线调音的直接替代'),
 'xiph/rnnoise': ('技术参考', '固定帧神经降噪；只列未来候选，保留现有立体声算法'),
 'breakfastquay/rubberband': ('技术参考', '离线/实时伸缩 API、延迟与共振峰；GPL/商业授权需决定后再链接'),
 'rspeyer/soundtouch': ('技术参考', 'SoundTouch API 的节奏/音高分离；镜像活跃度需谨慎，不直接引入旧实现'),
 'aubio/aubio': ('技术参考', 'YIN 谷值候选；GPL 不作为无许可证项目的可任意复制实现'),
 'librosa/librosa': ('技术参考', '音高概率/连续性；继续以既有 NumPy/SciPy 栈降低依赖体积'),
 'spotify/basic-pitch': ('技术参考', '音符推理和模型加载；不将其演唱转 MIDI 能力伪装成本轮已实现'),
 'csteinmetz1/pyloudnorm': ('技术参考', '门限响度测量；参考独立标定，保留原 LUFS 回归'),
 'FFmpeg/FFmpeg': ('技术参考', 'loudnorm 与编解码构建；保留音频专用 LGPL 动态库和源码义务'),
 'PyAV-Org/PyAV': ('直接依赖', '重采样模块；运行 wheel 与发布编解码器必须分别核查'),
 'spatialaudio/python-sounddevice': ('直接依赖', 'PortAudio Python 封装；设备移除/索引变动不能只测默认设备'),
 'PortAudio/portaudio': ('直接依赖', 'C API 与宿主后端；Linux/macOS 系统依赖进入 CI'),
 'juce-framework/JUCE': ('技术参考', '过采样处理器与原生音频生态；现有 Qt 主循环不替换为另一套框架'),
 'steinbergmedia/vst3sdk': ('技术参考', 'SDK CMake 组件边界；插件沙箱、崩溃隔离与商标规则成本高，延期'),
 'pyinstaller/pyinstaller': ('构建依赖', '冻结 Analysis/构建入口；桌面与控制台启动器分别打包'),
 'obsproject/obs-studio': ('相邻竞品', '原生模块化构建与发行；参考发布自动化，不引入直播产品范围'),
 'falkTX/Carla': ('相邻竞品', '插件宿主构建；许可未明确的快照只作研究，不复制'),
 'DISTRHO/DPF': ('技术参考', '小型跨平台插件框架；参考边界，暂不扩张插件支持'),
 'muse-sequencer/muse': ('相邻竞品', 'src 原生编辑器构建；MIDI 音序不作为核心需求'),
 'wwmm/easyeffects': ('相邻竞品', 'Qt/CMake 和 Linux 音频链；源码布局已变化，不能沿用旧 Meson 假设'),
 'bmc0/dsp': ('技术参考', 'effects_chain C 管线；命令行可组合处理启发本轮批处理入口'),
}
CANDIDATES = [
 ('四 runner 原生 CI', 'PyInstaller/跨平台桌面构建', 'P0', '中', '实施'),
 ('Ruff 与版本一致性门禁', '原项目三处版本重复', 'P0', '低', '实施'),
 ('固定 Action SHA', 'GitHub 官方工作流安全', 'P0', '低', '实施'),
 ('main 分支保护', '原仓库无保护', 'P0', '低', '实施'),
 ('最小工作流权限', 'GitHub 官方权限模型', 'P0', '低', '实施'),
 ('Dependabot 周期依赖提案', '持续维护需求', 'P1', '低', '实施'),
 ('依赖漏洞扫描与 PR 审查', '第三方数值/编解码运行库', 'P0', '中', '实施'),
 ('Issue/PR/CODEOWNERS', '可复现设备和更新故障', 'P1', '低', '实施'),
 ('私密漏洞报告', '音频文件解析安全', 'P0', '低', '实施'),
 ('统一版本命令', 'PyInstaller/Inno 双入口', 'P1', '低', '实施'),
 ('版本化资产命名', '多平台分发可追踪性', 'P1', '低', '实施'),
 ('标签自动构建发布', '桌面项目自动化构建', 'P0', '高', '实施'),
 ('Ed25519 更新清单', '版本字符串不能认证安装器', 'P0', '高', '实施'),
 ('严格来源与重定向限制', 'GitHub 官方资产分发', 'P0', '中', '实施'),
 ('下载上限/磁盘检查/原子提交', '模型中心已有安全传输原则', 'P0', '中', '实施'),
 ('安装前重新哈希', '下载后缓存被修改', 'P0', '低', '实施'),
 ('官方更新说明与下载进度', '成熟桌面更新交互', 'P1', '中', '实施'),
 ('安装自动回滚/启动健康检查', '完整更新生命周期', 'P1', '高', '延期：需事务安装器与真实故障验收'),
 ('Authenticode', 'Windows 系统来源验证', 'P1', '中', '阻塞：无证书'),
 ('macOS 签名/公证 DMG', 'Qt 原生平台分发', 'P1', '高', '阻塞：无 Developer ID/实机'),
 ('Linux AppImage/DEB/RPM', 'Ardour/Tenacity 分发', 'P2', '高', '延期：发行版和编解码许可验收'),
 ('XDG/Application Support', '平台原生文件规范', 'P1', '低', '实施'),
 ('系统字体与默认设备文案', 'Qt 桌面交互', 'P1', '低', '实施'),
 ('条件 ONNX/PE 依赖', 'DirectML 仅限 Windows', 'P0', '中', '实施'),
 ('CLI 分析 JSON', 'bmc0/dsp 管线与离线测量', 'P1', '中', '实施'),
 ('串行批量调音/失败隔离', 'audio-separator 批处理思路', 'P1', '中', '实施'),
 ('CLI 防覆盖与碰撞报告', '现有 audioio 非破坏原则', 'P0', '低', '实施'),
 ('独立控制台 EXE', 'PyInstaller GUI 无控制台限制', 'P1', '低', '实施'),
 ('每月上游证据工件', '框架/项目近期迁移观察', 'P2', '中', '实施'),
 ('完整平台/维护仪表盘', '原文档仅 Windows', 'P1', '低', '实施'),
 ('RNNoise 推理集成', 'RNNoise 固定帧设计', 'P2', '高', '延期：立体声与音质听审'),
 ('Rubber Band 共振峰保护', 'Rubber Band API', 'P2', '高', '延期：授权与音质比较'),
 ('VST3 插件隔离', 'Carla/VST3 SDK', 'P3', '高', '延期：宿主与沙箱维护成本'),
 ('MIDI/谱面导出', 'Basic Pitch/MuseScore', 'P3', '高', '不实施：超出核心定位'),
 ('Web 上传任务服务', 'Voice Changer 服务架构', 'P3', '高', '不实施：离线隐私与运维范围变化'),
 ('移动触控工作站', '桌面项目平台差异', 'P3', '高', '延期：独立 UI/音频会话和设备资源'),
]


def main():
    evidence = json.loads((ROOT / 'docs/evidence-020/upstreams.json').read_text('utf-8'))
    rows = ['# 上游研究、差距与实施决定\n',
        '观察时间：' + evidence['observed_at'] + '。证据为 GitHub API 实际返回；Stars/Forks 是该时点快照。'
        '逐仓读取 README、根目录、一个主源码/构建入口、最新提交、前三个开放 Issue 和最新 Release。'
        '这是结构抽查，不是对每个项目的全部代码审计。原始字段和失败请求保留在 [upstreams.json](evidence-020/upstreams.json)。'
        'NOASSERTION/null 表示 API 无法判定许可，不能解释为没有许可或允许复制；本轮没有导入研究项目代码。\n',
        '| 项目/证据 | 分类/技术 | Stars/Forks | 最近提交/活跃窗口 | 最新 Release | API 许可证 | 价值与决定 |',
        '|---|---|---|---|---|---|---|']
    observed = dt.datetime.fromisoformat(evidence['observed_at'])
    successful = 0
    for p in evidence['projects']:
        if not p.get('source_read'):
            continue
        successful += 1
        repo = p['repository']
        kind, decision = INSIGHTS.get(repo, ('技术参考', '仅保留证据，未吸收代码'))
        when = p.get('commit_date') or p['pushed_at']
        days = (observed - dt.datetime.fromisoformat(when.replace('Z', '+00:00'))).days
        window = '30天内' if days <= 30 else '90天内' if days <= 90 else '180天内' if days <= 180 else '180天外'
        if p.get('archived'):
            window += '，已归档'
        releases = p.get('release')
        release = releases[0]['tag'] if isinstance(releases, list) and releases else '无公开 Release/请求未得结果'
        rows.append(f"| [{repo}]({p['source_url']}) | {kind} / {p.get('language')} | {p['stars']}/{p['forks']} | {when[:10]} / {window} | {release} | {p.get('license')} | {decision} |")
    rows += [f'\n成功读取源码入口 **{successful}** 个；其余请求如实列在证据中，不计入成功项目。',
        '\n## 证据限制与近期观察\n',
        '每个仓库的前三个开放 Issue 只用于发现问题线索，不能据此宣称某需求“高频”。'
        'Release 日期、名称、最新提交日期和归档状态均来自 API。30/90/180 天窗口表示最后一次提交时间，不能冒充完整活动统计或最近新增功能清单。'
        'Zrythm/EasyEffects 当前根目录使用 CMake，旧 Meson 路径请求返回 404 后已重新核查；Demucs 归档状态需作为长期依赖风险。'
        'ONNX Runtime 仓库 API 返回 404，故本轮改查官方执行提供程序文档，并以本地 wheel 实际推理为独立证据。'
        '模型权重、测试语料与原生库的许可各自独立，不能因 Python 包 MIT 就自动推断权重允许再分发。\n',
        '## 功能差距和 UI/架构决定\n',
        '| 维度 | 本项目起点 | 参考实现 | 本轮决定 |',
        '|---|---|---|---|',
        '| 非破坏音频编辑 | 已有帧坐标、引用素材、撤销 | Audacity/Ardour 原生桌面 | 保留并纳入原有回归 |',
        '| 模型多后端 | 已有固定 ONNX、子进程回退 | UVR/Spleeter/audio-separator 调度边界 | 继续共享服务，暂不增加未验收模型 |',
        '| 批处理 | 无公开 CLI | bmc0/dsp 处理链、分离器门面 | 新增同引擎 CLI，结构化结果、失败隔离 |',
        '| 平台分发 | 只有 Windows 本地脚本 | CMake 原生项目和 PyInstaller | 先原生 CI/源码适配，不用套壳或空安装包 |',
        '| 更新 | 自定义版本字符串查询 | 官方 GitHub Releases + 独立密码签名设计 | 新增可验证下载；自动回滚独立延期 |',
        '| UI | 既有工作台、曲线与效果器 | Audacity 分析/编辑边界、Ardour 会话 | 保留视觉语言；更新窗口只显示版本、说明和操作进度 |',
        '\n关键技术收益是把批处理和平台规则从主窗口中分离，沿用 service 的事务提交语义。'
        '没有借入竞品品牌、素材、界面资源或 GPL/商业音频算法。未打开实际竞品 GUI，不能宣称完成其视觉可用性实测。\n',
        '## 升级候选（优先级、成本与实施）\n',
        '| 编号 | 具体升级 | 参考依据/价值 | 优先级 | 难度 | 决定 |',
        '|---|---|---|---|---|---|']
    rows += [f'| {i:02d} | ' + ' | '.join(c) + ' |' for i, c in enumerate(CANDIDATES, 1)]
    rows += ['\n“实施”表示本轮写入实现或配置，实际 PASS/FAIL/BLOCKED 见 [交付记录](DELIVERY-020.md)。'
        '每月 Upstream research 工作流保存证据工件，维护者审核差异后再决定任务；重大版本需重新深度核查许可证、源码和真实设备。\n']
    (ROOT / 'docs/RESEARCH-020.md').write_text('\n'.join(rows), 'utf-8')
    print('Documented', successful, 'source reviews and', len(CANDIDATES), 'upgrade candidates')


if __name__ == '__main__':
    main()
