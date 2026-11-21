"""Recovery checkpoints keep project media reachable after a directory move."""

import os
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from vox import storage


def media_references(data):
    return (
        data["source"], data["reference"], data["stems"]["Vocal"],
        data["stems"]["Instrumental"], data["studio"]["external_sources"]["dub"],
    )


def test_history_rebases_all_media_and_survives_moving_project_tree(tmp_path):
    bundle = tmp_path / "original bundle"
    project = bundle / "work" / "mix.voxproj"
    media = (
        project.parent / "media" / "source.wav",
        bundle / "reference.wav",
        project.parent / "media" / "voice.wav",
        project.parent / "media" / "backing.wav",
        bundle / "external" / "dub.wav",
    )
    for index, path in enumerate(media):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"media {index}".encode())

    old = storage.project("media/source.wav", "Original edit")
    old["reference"] = str(Path("..") / "reference.wav")
    old["stems"] = {"Vocal": str(media[2]), "Instrumental": "media/backing.wav"}
    old["studio"] = {"schema": 1, "external_sources": {"dub": "../external/dub.wav"}}
    old["history"] = ["original step"]
    storage.write_json(project, old)
    new = storage.load_project(project)
    new["name"] = "New edit"
    storage.save_project(project, new)

    checkpoint, = (project.parent / (project.name + ".history")).glob("*.voxproj")
    checkpoint_raw = storage.read_json(checkpoint)
    assert media_references(storage.load_project(checkpoint)) == tuple(str(p.resolve()) for p in media)

    moved = tmp_path / "moved bundle"
    bundle.rename(moved)
    moved_checkpoint = moved / checkpoint.relative_to(bundle)
    recovered = storage.load_project(moved_checkpoint)
    moved_media = tuple((moved / p.relative_to(bundle)).resolve() for p in media)
    assert media_references(recovered) == tuple(map(str, moved_media))
    assert [Path(ref).read_bytes() for ref in media_references(recovered)] == [
        f"media {index}".encode() for index in range(len(media))
    ]
    assert media_references(checkpoint_raw) == tuple(os.path.relpath(p, checkpoint.parent) for p in media)
    assert recovered["name"] == "Original edit"
    assert recovered["studio"]["schema"] == 1
    assert recovered["history"] == ["original step"]
    assert storage.load_project(moved / project.relative_to(bundle))["name"] == "New edit"


def test_linked_history_directory_rebases_against_actual_location(tmp_path):
    work, vault = tmp_path / 'work', tmp_path / 'vault' / 'history'
    work.mkdir()
    vault.mkdir(parents=True)
    media = work / 'voice.wav'
    media.write_bytes(b'original media')
    project = work / 'mix.voxproj'
    old = storage.project(media)
    storage.save_project(project, old)
    history = work / 'mix.voxproj.history'
    if os.name == 'nt':
        subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(history), str(vault)],
                       check=True, capture_output=True)
    else:
        history.symlink_to(vault, target_is_directory=True)
    changed = deepcopy(old)
    changed['name'] = 'new revision'
    storage.save_project(project, changed)
    backup, = vault.glob('*.voxproj')
    recovered = storage.load_project(backup.resolve())
    assert recovered['source'] == str(media.resolve())
    assert Path(recovered['source']).read_bytes() == b'original media'
    assert storage.load_project(project)['name'] == 'new revision'


def test_legacy_history_with_absolute_references_still_loads(tmp_path):
    media = tuple(tmp_path / f"legacy-{index}.wav" for index in range(5))
    for path in media:
        path.write_bytes(b"legacy media")
    source, reference, vocal, instrumental, dub = (str(p.resolve()) for p in media)
    raw = storage.project(source)
    raw.update(
        reference=reference,
        stems={"Vocal": vocal, "Instrumental": instrumental},
        studio={"external_sources": {"dub": dub}},
    )
    checkpoint = tmp_path / "legacy.voxproj.history" / "old.voxproj"
    storage.write_json(checkpoint, raw)

    assert media_references(storage.load_project(checkpoint)) == tuple(str(p.resolve()) for p in media)
    assert storage.read_json(checkpoint) == raw


@pytest.mark.skipif(os.name != "nt", reason="Windows drive letters required")
def test_rebasing_across_drives_keeps_resolved_absolute_paths(tmp_path):
    before = tmp_path.resolve() / "project"
    # No files or mounts are needed on the destination drive for relpath.
    other_drive = "Z:" if before.drive.upper() != "Z:" else "Y:"
    after = Path(other_drive + r"\mix.voxproj.history")
    raw = storage.project("media/source.wav")
    raw["stems"] = {"Vocal": "../voice.wav", "empty": ""}
    raw["studio"] = {"external_sources": {"dub": str(before / "external/dub.wav")}}
    original = deepcopy(raw)

    rebased = storage.data_at_location(raw, before, after)

    assert rebased["source"] == str((before / "media/source.wav").resolve())
    assert rebased["reference"] == ""
    assert rebased["stems"] == {"Vocal": str((before / "../voice.wav").resolve()), "empty": ""}
    assert rebased["studio"] == {"external_sources": {"dub": str(before / "external/dub.wav")}}
    assert raw == original
