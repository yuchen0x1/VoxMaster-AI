"""External timeline media obeys the same reconstruction transaction as the source."""
from copy import deepcopy
import os
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from vox import audioio, service
from vox.storage import load_project, project, save_project
from vox.studio_session import Session as MixSession


def tone(frequency, seconds=.25):
    t = np.arange(round(service.SR * seconds)) / service.SR
    wave = .08 * np.sin(2 * np.pi * frequency * t)
    return np.column_stack((wave, wave)).astype(np.float32)


def external_project(tmp_path, count=1):
    source = tone(180)
    path = tmp_path / 'source.wav'
    audioio.encode(path, source, service.SR, 32)
    doc = project(str(path))
    timeline = MixSession({'Vocal': source}, service.SR)
    for index in range(count):
        samples = tone(440 + index * 110)
        external = tmp_path / f'external-{index}.wav'
        audioio.encode(external, samples, service.SR, 32)
        timeline.import_clip('FX', f'fx-{index}', str(external), samples, index * len(samples))
    doc['studio'] = timeline.saved_state()
    return doc


def replace_same_stat(path):
    path = Path(path)
    before = path.stat()
    replacement = path.with_name('replacement.wav')
    audioio.encode(replacement, tone(880), service.SR, 32)
    os.replace(replacement, path)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns


def test_same_stat_external_replacement_reloads_and_matches_reopen(tmp_path):
    doc = external_project(tmp_path)
    current = service.prepare(doc, Event(), lambda *_: None)
    original_output = current.output.copy()
    original_doc = deepcopy(current.document)
    external = doc['studio']['external_sources']['fx-0']
    replace_same_stat(external)
    changed = service.prepare(doc, Event(), lambda *_: None, current)
    assert changed.external_cache['fx-0'][1] is not current.external_cache['fx-0'][1]
    assert changed.media_hashes['external/fx-0'] == service.file_hash(external)
    assert not np.array_equal(changed.output, original_output)
    saved = tmp_path / 'edited.voxproj'
    save_project(saved, changed.document)
    reopened = service.prepare(load_project(saved), Event(), lambda *_: None)
    np.testing.assert_array_equal(changed.output, reopened.output)
    np.testing.assert_array_equal(current.output, original_output)
    assert current.document == original_doc


@pytest.mark.parametrize('mutation', ['replace', 'delete'])
def test_external_change_during_render_rejects_draft_and_preserves_previous(tmp_path, mutation):
    doc = external_project(tmp_path)
    current = service.prepare(doc, Event(), lambda *_: None)
    previous_doc = deepcopy(current.document)
    previous_output = current.output.copy()
    external = Path(doc['studio']['external_sources']['fx-0'])
    changed = []

    def progress(fraction, message):
        if fraction == .92 and not changed:
            if mutation == 'replace':
                replace_same_stat(external)
            else:
                external.unlink()
            changed.append(True)

    with pytest.raises((ValueError, FileNotFoundError)):
        service.prepare(doc, Event(), progress, current)
    assert changed
    assert current.document == previous_doc
    np.testing.assert_array_equal(current.output, previous_output)


def test_external_cache_reuse_requires_matching_identity_for_each_source(tmp_path):
    doc = external_project(tmp_path, count=2)
    current = service.prepare(doc, Event(), lambda *_: None)
    same = service.prepare(doc, Event(), lambda *_: None, current)
    for key, path in doc['studio']['external_sources'].items():
        assert same.external_cache[key][1] is current.external_cache[key][1]
        assert same.media_hashes['external/' + key] == service.file_hash(path)
    replace_same_stat(doc['studio']['external_sources']['fx-1'])
    changed = service.prepare(doc, Event(), lambda *_: None, same)
    assert changed.external_cache['fx-0'][1] is same.external_cache['fx-0'][1]
    assert changed.external_cache['fx-1'][1] is not same.external_cache['fx-1'][1]


def test_relinked_external_source_and_removed_clip_do_not_keep_stale_cache(tmp_path):
    doc = external_project(tmp_path)
    current = service.prepare(doc, Event(), lambda *_: None)
    alternate = tmp_path / 'alternate.wav'
    audioio.encode(alternate, tone(990), service.SR, 32)
    changed_doc = deepcopy(doc)
    changed_doc['studio']['external_sources']['fx-0'] = str(alternate)
    changed = service.prepare(changed_doc, Event(), lambda *_: None, current)
    assert changed.external_cache['fx-0'][1] is not current.external_cache['fx-0'][1]
    changed_doc['studio']['external_sources'] = {}
    changed_doc['studio']['tracks']['FX']['clips'] = []
    removed = service.prepare(changed_doc, Event(), lambda *_: None, changed)
    assert removed.external_cache == {}
    assert not any(key.startswith('external/') for key in removed.media_hashes)


def test_old_session_without_external_hash_reloads_once(tmp_path):
    doc = external_project(tmp_path)
    current = service.prepare(doc, Event(), lambda *_: None)
    current.media_hashes.pop('external/fx-0', None)
    current.file_signatures.pop('external/fx-0', None)
    refreshed = service.prepare(doc, Event(), lambda *_: None, current)
    assert refreshed.external_cache['fx-0'][1] is not current.external_cache['fx-0'][1]
    np.testing.assert_array_equal(refreshed.output, current.output)


def test_cancel_while_hashing_external_media_preserves_previous(tmp_path, monkeypatch):
    doc = external_project(tmp_path)
    current = service.prepare(doc, Event(), lambda *_: None)
    cancel = Event()
    original_hash = service.file_hash
    external = doc['studio']['external_sources']['fx-0']

    def cancelled_hash(path, event=None):
        if str(path) == external:
            cancel.set()
        return original_hash(path, event)

    monkeypatch.setattr(service, 'file_hash', cancelled_hash)
    with pytest.raises(InterruptedError):
        service.prepare(doc, cancel, lambda *_: None, current)
    assert current.document == doc
    assert current.output is not None
