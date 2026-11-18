"""Factory starting points and ranges shared by the renderer and the controls."""

from copy import deepcopy

STAGES = dict(
    denoise="底噪抑制",
    pitch="旋律音高",
    eq="参数均衡",
    compress="动态压缩",
    deess="齿音控制",
    saturate="谐波塑形",
    space="空间与尾音",
    stereo="立体声",
    master="响度与峰值",
)
# Label, minimum, maximum, editing increment.
PARAMS = {
    "denoise": ("降噪力度", 0, 1, 0.05),
    "highpass_hz": ("高通 Hz", 20, 450, 1),
    "body_db": ("低频厚度 dB", -9, 9, 0.1),
    "mud_db": ("低中频 dB", -9, 9, 0.1),
    "presence_db": ("咬字清晰度 dB", -9, 9, 0.1),
    "air_db": ("空气感 dB", -9, 9, 0.1),
    "body_hz": ("厚度频率 Hz", 60, 300, 1),
    "mud_hz": ("低中频频率 Hz", 150, 1000, 1),
    "presence_hz": ("清晰频率 Hz", 1200, 6500, 10),
    "air_hz": ("高架频率 Hz", 4500, 14000, 10),
    "eq_q": ("钟形带宽 Q", 0.35, 4, 0.05),
    "threshold_db": ("压缩阈值 dB", -60, 0, 0.5),
    "ratio": ("压缩比", 1, 12, 0.1),
    "attack_ms": ("启动 ms", 1, 150, 1),
    "release_ms": ("释放 ms", 15, 600, 5),
    "knee_db": ("软拐点 dB", 0, 18, 0.5),
    "makeup_db": ("补偿 dB", -6, 12, 0.5),
    "deess": ("齿音抑制", 0, 1, 0.05),
    "drive": ("饱和力度", 0, 1, 0.05),
    "reverb": ("混响发送", 0, 0.7, 0.01),
    "decay_s": ("混响衰减 s", 0.12, 5, 0.05),
    "predelay_ms": ("预延迟 ms", 0, 160, 1),
    "size": ("空间尺寸", 0.4, 1.8, 0.05),
    "damping": ("高频阻尼", 0, 1, 0.05),
    "wet_low_hz": ("返回低切 Hz", 45, 1200, 5),
    "wet_high_hz": ("返回高切 Hz", 1500, 16000, 100),
    "wet_width": ("返回宽度", 0, 1.8, 0.05),
    "dry": ("直接声", 0, 1, 0.01),
    "delay": ("句尾延迟发送", 0, 0.8, 0.01),
    "delay_ms": ("延迟 ms", 40, 1200, 5),
    "feedback": ("延迟反馈", 0, 0.78, 0.01),
    "tempo_bpm": ("同步速度 BPM", 40, 240, 0.1),
    "width": ("声像宽度", 0, 1.8, 0.05),
    "target_lufs": ("目标 LUFS", -30, -9, 0.5),
    "ceiling_db": ("真峰值上限 dBTP", -6, -0.3, 0.1),
    "pitch_strength": ("音准修正力度", 0, 1, 0.05),
    "pitch_speed_ms": ("音准响应 ms", 10, 300, 5),
    "semitones": ("移调 半音", -5, 5, 0.1),
}
DEFAULT = dict(
    denoise=0.25,
    highpass_hz=65,
    body_db=0.8,
    mud_db=-1,
    presence_db=1.5,
    air_db=0.7,
    body_hz=135,
    mud_hz=330,
    presence_hz=2900,
    air_hz=8200,
    eq_q=0.85,
    threshold_db=-18,
    ratio=2.5,
    attack_ms=15,
    release_ms=110,
    knee_db=6,
    makeup_db=1.2,
    deess=0.35,
    drive=0.12,
    saturation_type="Tape",
    reverb=0.10,
    decay_s=0.65,
    predelay_ms=18,
    size=1,
    damping=0.45,
    wet_low_hz=160,
    wet_high_hz=7600,
    wet_width=1.1,
    dry=1,
    room_type="Studio",
    reverb_send="Full",
    delay=0.13,
    delay_ms=180,
    feedback=0.26,
    delay_type="Ping-Pong",
    tempo_bpm=110,
    beat_fraction=0.5,
    width=1,
    target_lufs=-15,
    ceiling_db=-1.2,
    pitch_strength=0,
    pitch_speed_ms=85,
    semitones=0,
    scale="Chromatic",
    key="Auto",
    hum_hz=0,
    tail_times=[],
    order=list(STAGES),
    disabled=[],
)


def style(**changes):
    return {**deepcopy(DEFAULT), **changes}


PRESETS = {
    "经典喊麦": style(),
    "网络 MC": style(highpass_hz=85, presence_db=2.6, ratio=3.1, delay_ms=115, attack_ms=9),
    "热血喊麦": style(ratio=3.5, drive=0.32, body_db=1.6, attack_ms=24, target_lufs=-14),
    "厚重男声": style(highpass_hz=48, body_db=3.1, presence_db=1, drive=0.23, air_db=0.1),
    "清晰男声": style(mud_db=-2.3, presence_db=3, deess=0.45, reverb=0.06),
    "低沉磁性": style(
        highpass_hz=42, body_db=2.8, air_db=-1.4, presence_db=0.8, drive=0.35, saturation_type="Tube"
    ),
    "明亮穿透": style(presence_db=3.3, air_db=2.8, deess=0.53, body_db=-0.8),
    "霸气力量感": style(body_db=2, ratio=3.8, attack_ms=30, drive=0.39, reverb=0.05),
    "史诗空间感": style(
        room_type="Large Space", reverb=0.23, decay_s=2.3, size=1.55, predelay_ms=48, delay=0.24
    ),
    "干净录音棚": style(
        room_type="Studio", reverb=0.05, decay_s=0.35, drive=0.03, delay=0, ratio=1.8
    ),
    "电子喊麦": style(
        room_type="Plate",
        reverb=0.14,
        delay=0.3,
        feedback=0.45,
        drive=0.34,
        saturation_type="Exciter",
    ),
    "旋律喊麦": style(
        room_type="Plate", pitch_strength=0.47, release_ms=170, reverb=0.16, decay_s=1.25, delay=0.19
    ),
    "Rap": style(
        highpass_hz=82, reverb=0.035, delay=0.09, presence_db=2.4, attack_ms=8, release_ms=70
    ),
    "情绪化人声": style(
        room_type="Dark Hall", reverb=0.17, decay_s=1.65, ratio=1.6, attack_ms=32, drive=0.08
    ),
    "远距离空间": style(
        room_type="Hall", dry=0.87, reverb=0.34, decay_s=1.8, predelay_ms=7, air_db=-1.7, size=1.35
    ),
    "近距离干声": style(reverb=0, delay=0, drive=0.05, body_db=1.4, width=0.9, deess=0.42),
    "广播电台": style(
        body_db=2.7, mud_db=-1.8, ratio=4, attack_ms=6, release_ms=75, drive=0.24, reverb=0, delay=0
    ),
    "复古效果": style(
        saturation_type="Radio",
        drive=0.6,
        room_type="Spring",
        reverb=0.10,
        delay_ms=90,
        delay=0.2,
        width=0.72,
    ),
}
