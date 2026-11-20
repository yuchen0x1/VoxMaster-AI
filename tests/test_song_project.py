from copy import deepcopy
import json
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from vox import audioio, service
from vox.storage import load_project, project, save_project, write_json


FIXTURE = Path(__file__).parent / "fixtures" / "fleurs-mandarin.wav"


def stems(tmp_path):
    voice, _ = audioio.decode(FIXTURE)
    voice = voice[: 2 * service.SR] * np.float32(0.55)
    t = np.arange(len(voice)) / service.SR
    instrument = np.column_stack((0.12 * np.sin(2 * np.pi * t * 220),
                                  0.10 * np.sin(2 * np.pi * t * 330))).astype(np.float32)
    for name, data in {"mix": voice + instrument, "Vocal": voice, "Instrumental": instrument}.items():
        audioio.encode(tmp_path / (name + ".wav"), data, service.SR, 32)
    doc = project(tmp_path / "mix.wav")
    doc["stems"] = {k: str(tmp_path / (k + ".wav")) for k in ("Vocal", "Instrumental")}
    return doc


def test_song_plan_round_trip_does_not_mutate_stems_and_recalls_exact_mix(tmp_path):
    original = stems(tmp_path)
    cancel = Event()
    seen = []
    progress = lambda fraction, msg: seen.append(fraction)
    dry = service.prepare(original, cancel, progress)
    assert dry.output is None
    checksums = {k: Path(v).read_bytes() for k, v in original["stems"].items()}
    wet = service.plan_song(dry, cancel, progress, target="clear", master="standard")
    assert wet.document["mode"] == "song" and dry.document == original
    assert wet.output.shape == dry.original.shape and not np.array_equal(wet.output, dry.original)
    assert wet.measured["true_peak_db"] <= wet.document["song"]["ceiling_db"] + .025
    assert wet.audit["song"]["before_master"]["lufs"] > -70
    assert "master" not in wet.audit["stages"]
    assert set(wet.mix_sources) == {"Vocal", "Instrumental"}
    unsafe = deepcopy(wet.document)
    unsafe["params"]["disabled"].remove("master")
    resequenced = service.prepare(unsafe, cancel, progress, dry)
    assert "master" not in resequenced.audit["stages"]
    path = tmp_path / "arrangement.voxproj"
    save_project(path, wet.document)
    assert json.loads(path.read_text("utf-8"))["source"] == "mix.wav"
    recalled = service.prepare(load_project(path), cancel, progress)
    np.testing.assert_array_equal(recalled.output, wet.output)
    assert recalled.document["song"] == wet.document["song"]
    assert all(Path(v).read_bytes() == checksums[k] for k, v in original["stems"].items())
    assert max(seen) == 1.0


def test_legacy_project_and_recovery_checkpoint_keep_separate_behaviour(tmp_path):
    doc = stems(tmp_path)
    dry_path = tmp_path / "legacy.voxproj"
    save_project(dry_path, doc)
    dry = service.prepare(load_project(dry_path), Event(), lambda *_: None)
    assert "mode" not in dry.document and "song" not in dry.document and dry.output is None
    wet = service.plan_song(dry, Event(), lambda *_: None)
    save_project(dry_path, wet.document)
    checkpoint, = (tmp_path / "legacy.voxproj.history").glob("*.voxproj")
    old = load_project(checkpoint)
    assert old["stems"] == doc["stems"] and "song" not in old
    broken = deepcopy(wet.document)
    broken["song"]["ceiling_db"] = "invalid"
    write_json(tmp_path / "broken.voxproj", broken)
    with pytest.raises(ValueError):
        load_project(tmp_path / "broken.voxproj")


def test_plan_refuses_replaced_stem_and_cancellation(tmp_path):
    doc = stems(tmp_path)
    cancel = Event()
    dry = service.prepare(doc, cancel, lambda *_: None)
    cancel.set()
    with pytest.raises(InterruptedError):
        service.plan_song(dry, cancel, lambda *_: None)
    cancel.clear()
    with Path(doc["stems"]["Vocal"]).open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="已变更"):
        service.plan_song(dry, cancel, lambda *_: None)
