"""Transactional project reconstruction. Only completed results reach the window."""

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
from . import audioio, engine
from .acoustics import extra_features
from .quality import assess, quality_metrics, validate_buffer
from .reference import match_segments, measure_role_space
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


def check(cancel):
    if cancel.is_set():
        raise InterruptedError()


def measure(samples, cancel):
    from .segments import analyze_segments

    report = engine.analyze(samples, SR, cancel)
    report.update(extra_features(samples, SR, report, cancel))
    report["segments"] = analyze_segments(samples, SR, report, cancel)
    report.update(quality_metrics(samples, SR, report, cancel))
    report["role_space"] = measure_role_space(samples, SR, report, cancel)
    return report


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
    signatures = {}
    for key, path in paths.items():
        stat = Path(path).stat()
        signatures[key] = (str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns)

    def reusable(key):
        return previous is not None and previous.file_signatures.get(key) == signatures[key]

    if doc.get("applied"):
        doc["params"] = engine.normalize(doc["params"])
    if reusable("original"):
        session = Session(
            doc, previous.original, previous.metadata, previous.analysis, previous.original_wave
        )
    else:
        progress(0.02, "正在解码原始录音")
        raw, meta = audioio.decode(doc["source"], cancel)
        progress(0.12, "正在测量响度、动态和频谱")
        report = measure(raw, cancel)
        session = Session(doc, raw, meta, report, envelope(raw))
    check(cancel)
    session.file_signatures = signatures
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
    if not doc.get("applied") and doc.get("studio") is None:
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
    if doc.get("studio") is not None or len(session.sources) > 1:
        from .studio_session import Session as MixSession, load_sources

        progress(0.77, "正在渲染同步混音")
        tracks = dict(session.sources, Vocal=vocal)
        if doc.get("studio"):
            signatures = {}
            for key, path in doc["studio"].get("external_sources", {}).items():
                stat = Path(path).stat()
                signatures[key] = (path, stat.st_size, stat.st_mtime_ns)
                cached = previous.external_cache.get(key) if previous else None
                if cached and cached[0] == signatures[key]:
                    tracks[key] = cached[1]
            tracks = load_sources(doc["studio"], tracks, cancel=cancel)
            session.external_cache = {key: (sig, tracks[key]) for key, sig in signatures.items()}
        mix = MixSession(tracks, SR, state=doc.get("studio"))
        audio = mix.render(cancel=cancel)
        expected_frames = mix.frames
    else:
        audio = vocal
        expected_frames = len(session.sources["Vocal"])
    progress(0.86, "测量成品响度与真峰值")
    validate_buffer(audio, expected_frames, 2, cancel)
    measured = measure(audio, cancel)
    headroom = min(-0.1, float(doc.get("params", {}).get("ceiling_db", -1.0)))
    # Preserve legacy project gains. New renders honour their requested bus
    # ceiling even when accompaniment is added downstream of the vocal limiter.
    limit = headroom + 0.025 if "automation" in doc.get("params", {}) else -0.05
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
        doc.get("params", {}).get("target_lufs"),
        session.audit,
        aligned=not doc.get("studio"),
    )
    check(cancel)
    session.output = audio
    session.measured = measured
    session.output_wave = envelope(audio)
    progress(1.0, "渲染完成")
    return session
