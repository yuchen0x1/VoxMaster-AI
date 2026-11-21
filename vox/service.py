"""Transactional project reconstruction. Only completed results reach the window."""

from copy import deepcopy
from dataclasses import dataclass, field, replace
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import numpy as np
from . import audioio, engine, intelligence, song
from .quality import assess, validate_buffer
from .reference import match_segments
from .visual import envelope

SR = 44100


@dataclass
class Session:
    document: dict
    original: np.ndarray
    metadata: dict
    analysis: dict
    original_wave: np.ndarray
    sources: dict = field(default_factory=dict)
    output: np.ndarray | None = None
    measured: dict | None = None
    output_wave: np.ndarray | None = None
    reference_report: dict | None = None
    tuned_vocal: np.ndarray | None = None
    vocal_report: dict | None = None
    external_cache: dict = field(default_factory=dict)
    audit: dict = field(default_factory=dict)
    file_signatures: dict = field(default_factory=dict)
    instrumental_report: dict | None = None
    mix_sources: dict | None = None
    media_hashes: dict = field(default_factory=dict)
    publication_committed: bool = False
    publication_project: str | None = None


def check(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError()


def measure(samples, cancel):
    return intelligence.measure(samples, SR, cancel)


def signature(path):
    path = Path(path).resolve()
    stat = path.stat()
    return str(path), stat.st_size, stat.st_mtime_ns


def file_hash(path, cancel=None):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(262144):
            check(cancel)
            hasher.update(block)
    check(cancel)
    return hasher.hexdigest()


def check_media(paths, session, cancel):
    for key, path in paths.items():
        if (signature(path) != session.file_signatures[key]
                or file_hash(path, cancel) != session.media_hashes[key]):
            raise ValueError("处理期间素材已变更，未提交本次结果；请重新打开工程。")


def verify_separation(document, hashes):
    evidence = document.get("separation")
    if not evidence:
        return []
    identity = evidence.get("media_sha256", {})
    required = ("original", "stem/Vocal", "stem/Instrumental")
    valid = all(key in hashes and identity.get(key) == hashes[key] for key in required)
    if valid:
        return []
    # Keep no provider/reconstruction claims about relinked or unbound media.
    document["separation"] = {"status": "unverified", "reason": "media_identity_changed_or_missing"}
    return ["分离来源未验证或素材已替换；旧模型、后端和重建结果已失效，请重新分离核验。"]


def tuning_plan(report, style="经典喊麦", kind="自动判断", reference=None):
    if kind != "自动判断":
        report = dict(report, classification=kind, manual_type=kind)
    params = engine.recommend(report, style, reference)
    regions = params.get("automation", [])
    melodic = kind in ("旋律喊麦", "旋律型喊麦", "普通演唱")
    if melodic or (kind == "自动判断" and any(r.get("pitch_safe") for r in regions)):
        if params["pitch_strength"] == 0:
            params["pitch_strength"] = 0.4 if melodic else 0.25
    else:
        params["pitch_strength"] = 0.0
    if kind == "纯伴奏":
        params["disabled"] = list(dict.fromkeys(params["disabled"] + ["pitch", "deess"]))
        params["tail_times"] = []
        params["tail_regions"] = []
    if reference:
        params = match_segments(params, report, reference)
    return params


def prepare(doc, cancel, progress, previous=None):
    doc = deepcopy(doc)
    paths = {"original": doc["source"]}
    if doc.get("reference"):
        paths["reference"] = doc["reference"]
    paths.update({"stem/" + name: path for name, path in doc.get("stems", {}).items()})
    external = (doc.get("studio") or {}).get("external_sources", {})
    paths.update({"external/" + key: path for key, path in external.items()})
    signatures = {key: signature(path) for key, path in paths.items()}
    hashes = {key: file_hash(path, cancel) for key, path in paths.items()}
    provenance_warnings = verify_separation(doc, hashes)
    plan = doc.get("song")
    if plan is not None:
        plan = doc["song"] = song.validate_plan(plan)
        if not all(doc.get("stems", {}).get(key) for key in ("Vocal", "Instrumental")):
            raise ValueError("歌曲方案需要人声与伴奏两条分轨。")

    def reusable(key):
        return (
            previous is not None
            and previous.file_signatures.get(key) == signatures[key]
            and previous.media_hashes.get(key) == hashes[key]
        )

    if plan is not None and not doc.get("applied"):
        raise ValueError("整曲方案要求先显式应用人声与最终母带参数。")
    if doc.get("applied"):
        params = engine.normalize(doc["params"])
        if plan is not None:
            # The song master belongs after the full Studio render, never on vocal alone.
            params["disabled"] = list(dict.fromkeys(params["disabled"] + ["master"]))
        doc["params"] = engine.normalize(params)
    if reusable("original"):
        session = Session(
            doc, previous.original, previous.metadata, previous.analysis, previous.original_wave
        )
    else:
        progress(0.02, "正在解码原始录音")
        raw, meta = audioio.decode(doc["source"], cancel)
        progress(0.12, "正在测量响度、动态和频谱")
        report = intelligence.inspect_file(measure(raw, cancel), meta)
        session = Session(doc, raw, meta, report, envelope(raw))
    check(cancel)
    session.file_signatures = signatures
    session.media_hashes = hashes
    if doc.get("reference"):
        if reusable("reference"):
            session.reference_report = previous.reference_report
        else:
            progress(0.23, "分析参考音频")
            ref, _ = audioio.decode(doc["reference"], cancel)
            session.reference_report = measure(ref, cancel)
    session.sources = {"Vocal": session.original}
    for name, path in doc.get("stems", {}).items():
        if reusable("stem/" + name):
            session.sources[name] = previous.sources[name]
        else:
            session.sources[name] = audioio.decode(path, cancel)[0]
    if doc.get("stems", {}).get("Vocal"):
        if previous and previous.sources.get("Vocal") is session.sources["Vocal"]:
            session.vocal_report = previous.vocal_report
        else:
            session.vocal_report = measure(session.sources["Vocal"], cancel)
    if plan is not None:
        if previous and previous.sources.get("Instrumental") is session.sources["Instrumental"]:
            session.instrumental_report = previous.instrumental_report
        if session.instrumental_report is None:
            session.instrumental_report = intelligence.metrics(session.sources["Instrumental"], SR, cancel)
        generated_pair = doc.get("separation", {}).get("status") == "verified"
        for key in ("Vocal", "Instrumental"):
            frames = len(session.original) if generated_pair else len(session.sources[key])
            validate_buffer(session.sources[key], frames, 2, cancel)
    if not doc.get("applied") and doc.get("studio") is None and plan is None:
        session.audit["warnings"] = provenance_warnings
        check_media(paths, session, cancel)
        return session
    vocal = session.sources["Vocal"]
    if doc.get("applied"):
        if (
            previous
            and previous.sources.get("Vocal") is vocal
            and previous.tuned_vocal is not None
            and previous.document["params"] == doc["params"]
        ):
            vocal = previous.tuned_vocal
            session.audit = deepcopy(previous.audit)
            session.audit.pop("output_warnings", None)
            session.audit.pop("peak_trim_db", None)
        else:
            vocal = engine.process(
                vocal,
                SR,
                doc["params"],
                cancel,
                lambda f, m: progress(0.27 + 0.48 * f, m),
                audit=session.audit,
            )
        validate_buffer(vocal, len(session.sources["Vocal"]), 2, cancel)
        session.tuned_vocal = vocal
    check(cancel)
    session.audit["warnings"] = list(dict.fromkeys(session.audit.get("warnings", []) + provenance_warnings))
    if plan is not None and len(session.sources["Vocal"]) != len(session.sources["Instrumental"]):
        session.audit["warnings"].append("外部分轨按共同起点对齐，保留较长轨尾部；请在多轨工作室核对起点与尾音。")
    if doc.get("studio") is not None or len(session.sources) > 1:
        from .studio_session import Session as MixSession, load_sources

        tracks = dict(session.sources, Vocal=vocal)
        if plan is not None:
            progress(0.76, "处理人声与伴奏的相对电平及伴奏均衡")
            vocal_mix, music_mix = song.process_stems(vocal, tracks["Instrumental"], SR, plan, cancel)
            tracks.update(Vocal=vocal_mix, Instrumental=music_mix)
            session.mix_sources = dict(tracks)
        progress(0.79, "正在渲染同步混音")
        if doc.get("studio"):
            for key in external:
                cached = previous.external_cache.get(key) if previous else None
                if cached and reusable("external/" + key):
                    tracks[key] = cached[1]
            tracks = load_sources(doc["studio"], tracks, cancel=cancel)
            session.external_cache = {
                key: (signatures["external/" + key], tracks[key]) for key in external
            }
        mix = MixSession(tracks, SR, state=doc.get("studio"))
        audio = mix.render(cancel=cancel)
        expected_frames = mix.frames
    else:
        audio = vocal
        expected_frames = len(session.sources["Vocal"])
    validate_buffer(audio, expected_frames, 2, cancel)
    target = doc.get("params", {}).get("target_lufs")
    if plan is not None:
        progress(0.84, "处理混音总线母带及真峰值余量")
        before_master = intelligence.metrics(audio, SR, cancel)
        audio = song.master_mix(audio, SR, plan, cancel)
        validate_buffer(audio, expected_frames, 2, cancel)
        target = plan["target_lufs"]
        session.audit["song"] = {
            "plan": deepcopy(plan),
            "stems": {"Vocal": session.vocal_report, "Instrumental": session.instrumental_report},
            "before_master": before_master,
        }
    progress(0.92, "测量成品响度与真峰值")
    measured = measure(audio, cancel)
    headroom = plan["ceiling_db"] if plan is not None else min(
        -0.1, float(doc.get("params", {}).get("ceiling_db", -1.0))
    )
    # Preserve legacy project gains. New renders honour their requested bus
    # ceiling even when accompaniment is added downstream of the vocal limiter.
    limit = headroom + 0.025 if plan is not None or "automation" in doc.get("params", {}) else -0.05
    if measured["true_peak_db"] > limit:
        trim = headroom - measured["true_peak_db"]
        audio = audio * np.float32(10 ** (trim / 20))
        measured = measure(audio, cancel)
        session.audit["peak_trim_db"] = trim
    if measured["true_peak_db"] > limit + 0.025:
        raise ValueError("复测仍超出峰值余量，请降低总线增益再渲染。")
    session.audit["output_warnings"] = assess(
        session.analysis,
        measured,
        target,
        session.audit,
        aligned=not doc.get("studio"),
    )
    if plan is not None:
        if measured["stereo_correlation"] is not None and measured["stereo_correlation"] < -0.15:
            session.audit["output_warnings"].append("成品左右声道负相关，建议检查单声道兼容性。")
        if before_master["dynamic_db"] - measured["dynamic_db"] > 4:
            session.audit["output_warnings"].append("母带后活动帧动态收窄超过 4 dB，建议等响试听。")
    check(cancel)
    session.output = audio
    session.measured = measured
    session.output_wave = envelope(audio)
    check_media(paths, session, cancel)
    progress(1.0, "渲染完成")
    return session


def plan_song(current, cancel, progress, *, target="natural", master="conservative", style=None, plan=None):
    """Render the resolved song plan without altering the currently open session."""
    check(cancel)
    if not all(current.document.get("stems", {}).get(key) for key in ("Vocal", "Instrumental")):
        raise ValueError("请先准备人声和伴奏两条分轨。")
    for key, path in current.document["stems"].items():
        if (signature(path) != current.file_signatures.get("stem/" + key)
                or file_hash(path, cancel) != current.media_hashes.get("stem/" + key)):
            raise ValueError("分轨文件已变更，请重新打开工程后再分析。")
    if (signature(current.document["source"]) != current.file_signatures.get("original")
            or file_hash(current.document["source"], cancel) != current.media_hashes.get("original")):
        raise ValueError("原始音频已变更，请重新打开工程后再分析。")
    if style is None:
        style = current.document["style"]
    base_style = style if style in engine.PRESETS else "经典喊麦"
    vocal = current.vocal_report
    instrumental = current.instrumental_report
    if instrumental is None:
        progress(0.02, "正在测量伴奏频谱和动态")
        instrumental = intelligence.metrics(current.sources["Instrumental"], SR, cancel)
    doc = deepcopy(current.document)
    if not (doc.get("song") and doc.get("applied") and style == doc["style"]):
        doc["params"] = song.vocal_params(vocal, base_style, current.reference_report)
        doc.pop("before_reference", None)
    doc.update(
        mode="song", applied=True, style=style,
        song=song.recommend(vocal, instrumental, current.analysis, target, master)
        if plan is None else song.validate_plan(plan),
    )
    doc["history"].append("应用歌曲混音与母带方案")
    return prepare(doc, cancel, progress, replace(current, instrumental_report=instrumental))


def separate_project(current, destination, cancel, progress, *, root=None, mode=None, song_options=None):
    """Process locally with verified weights; publish a complete pair after a successful render."""
    from . import models_store, models_runtime

    check(cancel)
    source = current.document["source"]
    initial = current.file_signatures.get("original")
    source_digest = current.media_hashes.get("original")
    if signature(source) != initial or file_hash(source, cancel) != source_digest:
        raise ValueError("原始音频已变更，请重新导入后再分离。")
    root = Path(root) if root is not None else models_store.directory()
    mode = mode or models_store.settings().get("mode", "auto")
    audit = {
        "model": "Spleeter 2 stems",
        "revision": models_store.REVISION,
        "weights_sha256": {name: spec[1] for name, spec in models_store.FILES.items()},
        "requested_device": mode,
    }
    destination = Path(destination).resolve()
    folder = destination / ("vox-stems-" + uuid4().hex)
    with TemporaryDirectory(dir=destination, prefix=".vox-stems-") as tmp:
        # Keep the same depth as the published folder so relative project paths survive rename.
        staging = Path(tmp)
        vocal, music = models_runtime.separate(
            current.original, SR, cancel, lambda f, m: progress(0.63 * f, m),
            root=root, mode=mode, audit=audit,
        )
        audit["reconstruction"] = song.separation_evidence(current.original, vocal, music, SR, cancel)
        paths = {name: str(staging / (name + ".wav")) for name in ("Vocal", "Instrumental")}
        progress(0.65, "写入可恢复的原始分轨")
        export_warnings = []
        for name, data in (("Vocal", vocal), ("Instrumental", music)):
            exported = audioio.encode(paths[name], data, SR, 32, cancel)
            if exported.warning:
                export_warnings.append(exported.warning)
        del data, vocal, music
        audit.update(
            status="verified", sample_rate=SR, frames=len(current.original),
            media_sha256={"original": source_digest, **{
                "stem/" + name: file_hash(path, cancel) for name, path in paths.items()
            }},
        )
        doc = deepcopy(current.document)
        doc.update(stems=paths, studio=None, applied=False, params={}, separation=audit)
        doc.pop("song", None)
        doc.pop("before_reference", None)
        doc["history"].append("人声与伴奏分离 · " + audit["revision"][:8])
        progress(0.72, "分析原始分轨")
        result = prepare(doc, cancel, lambda f, m: progress(0.72 + 0.08 * f, m), current)
        if song_options is not None:
            result = plan_song(result, cancel, lambda f, m: progress(0.8 + 0.19 * f, m), **song_options)
        result.audit.setdefault("warnings", []).extend(export_warnings)
        if signature(source) != initial or file_hash(source, cancel) != source_digest:
            raise ValueError("分离期间原始音频发生变更，未保留本次分轨。")
        check(cancel)
        for name, path in result.document["stems"].items():
            final = str(folder / Path(path).name)
            result.document["stems"][name] = final
            _, size, mtime = result.file_signatures["stem/" + name]
            result.file_signatures["stem/" + name] = (final, size, mtime)
        from .storage import save_project

        # Publish a recovery project with the pair, independent of the GUI checkpoint.
        recovery = staging / "Separated.voxproj"
        recovery_doc = deepcopy(result.document)
        recovery_doc["stems"] = paths
        save_project(recovery, recovery_doc, False)
        check(cancel)
        staging.rename(folder)
        result.publication_project = str(folder / recovery.name)
        result.publication_committed = True
    progress(1.0, "分轨及处理完成" if song_options is not None else "分轨完成")
    return result
