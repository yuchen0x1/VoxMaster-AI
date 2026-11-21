"""External Studio media obey the same identity/commit boundary as original audio."""
from copy import deepcopy
import io
import os
from pathlib import Path
from threading import Event
import wave

import numpy as np
import pytest

from vox import audioio, service
from vox.storage import project
from vox.studio_session import Session as StudioSession


def tone_bytes(level, frequency=330):
    time = np.arange(service.SR // 2) / service.SR
    mono = np.rint(level * 32767 * np.sin(2 * np.pi * frequency * time)).astype('<i2')
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(service.SR)
        stream.writeframes(np.column_stack((mono, mono)).tobytes())
    return output.getvalue()


def external_document(tmp_path):
    source, effect = tmp_path / 'voice.wav', tmp_path / 'effect.wav'
    source.write_bytes(tone_bytes(.04, 220))
    effect.write_bytes(tone_bytes(.125))
    vocal, _ = audioio.decode(source)
    fx, _ = audioio.decode(effect)
    studio = StudioSession({'Vocal': vocal}, service.SR)
    studio.import_clip('FX', 'effect/one', effect, fx, 0)
    studio.state['tracks']['Vocal']['mute'] = True
    document = project(source)
    document['studio'] = studio.saved_state()
    return document, effect


def replace_preserving_signature(path, body):
    before = path.stat()
    assert len(body) == before.st_size
    path.write_bytes(body)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert path.stat().st_size == before.st_size


def test_same_signature_external_replacement_matches_cold_reopen(tmp_path):
    document, effect = external_document(tmp_path)
    original_document = deepcopy(document)
    current = service.prepare(document, Event(), lambda *_: None)
    previous_audio = current.output.copy()
    replace_preserving_signature(effect, tone_bytes(.25))

    rebuilt = service.prepare(document, Event(), lambda *_: None, current)
    reopened = service.prepare(document, Event(), lambda *_: None)

    np.testing.assert_array_equal(rebuilt.output, reopened.output)
    assert not np.array_equal(rebuilt.output, previous_audio)
    np.testing.assert_array_equal(current.output, previous_audio)
    assert current.document == document == original_document
    assert rebuilt.media_hashes['external/effect/one'] == service.file_hash(effect)
    assert rebuilt.external_cache['effect/one'][1] is not current.external_cache['effect/one'][1]


def test_unchanged_external_media_reuses_decoded_pcm(tmp_path, monkeypatch):
    document, effect = external_document(tmp_path)
    current = service.prepare(document, Event(), lambda *_: None)
    decoded = []
    decode = audioio.decode

    def observe(path, *args, **kwargs):
        decoded.append(str(path))
        return decode(path, *args, **kwargs)

    monkeypatch.setattr(audioio, 'decode', observe)
    rebuilt = service.prepare(document, Event(), lambda *_: None, current)
    assert decoded == []
    assert rebuilt.external_cache['effect/one'][1] is current.external_cache['effect/one'][1]
    np.testing.assert_array_equal(rebuilt.output, current.output)
    assert rebuilt.file_signatures['external/effect/one'] == service.signature(effect)


@pytest.mark.parametrize('fraction', [.02, .79, .92])
def test_external_replacement_during_render_refuses_commit(tmp_path, fraction):
    document, effect = external_document(tmp_path)
    current = service.prepare(document, Event(), lambda *_: None)
    previous_audio = current.output.copy()
    previous_document = deepcopy(current.document)
    changed = []

    def replace_during_work(value, _):
        if value == fraction and not changed:
            replace_preserving_signature(effect, tone_bytes(.25))
            changed.append(True)

    # Force original decoding at .02 as well as exercise the warm-cache paths.
    previous = None if fraction == .02 else current
    with pytest.raises(ValueError, match='处理期间素材已变更'):
        service.prepare(document, Event(), replace_during_work, previous)
    assert changed
    assert current.document == previous_document
    np.testing.assert_array_equal(current.output, previous_audio)


def test_old_session_without_external_hash_redecodes_safely(tmp_path):
    document, effect = external_document(tmp_path)
    current = service.prepare(document, Event(), lambda *_: None)
    current.media_hashes.pop('external/effect/one', None)
    current.file_signatures.pop('external/effect/one', None)
    replace_preserving_signature(effect, tone_bytes(.25))
    rebuilt = service.prepare(document, Event(), lambda *_: None, current)
    reopened = service.prepare(document, Event(), lambda *_: None)
    np.testing.assert_array_equal(rebuilt.output, reopened.output)


def test_removed_external_reference_drops_cache_and_identity(tmp_path):
    document, effect = external_document(tmp_path)
    current = service.prepare(document, Event(), lambda *_: None)
    changed = deepcopy(document)
    changed['studio']['external_sources'].clear()
    changed['studio']['tracks']['FX']['clips'].clear()
    effect.unlink()
    rebuilt = service.prepare(changed, Event(), lambda *_: None, current)
    assert rebuilt.external_cache == {}
    assert set(rebuilt.media_hashes) == {'original'}
    assert np.max(np.abs(rebuilt.output)) == 0


@pytest.mark.parametrize('role', ['Vocal', 'Instrumental'])
def test_external_reference_cannot_shadow_fresh_builtin_source(tmp_path, role):
    document, effect = external_document(tmp_path)
    original, _ = audioio.decode(document['source'])
    if role == 'Instrumental':
        document['stems']['Instrumental'] = document['source']
    studio = StudioSession({'Vocal': original, **(
        {'Instrumental': original} if role == 'Instrumental' else {})}, service.SR)
    studio.state['tracks']['Vocal']['mute'] = role != 'Vocal'
    document['studio'] = studio.saved_state()
    document['studio']['external_sources'][role] = str(effect)
    current = service.prepare(document, Event(), lambda *_: None)
    replace_preserving_signature(Path(document['source']), tone_bytes(.08, 220))

    rebuilt = service.prepare(document, Event(), lambda *_: None, current)
    reopened = service.prepare(document, Event(), lambda *_: None)
    np.testing.assert_array_equal(rebuilt.output, reopened.output)
    assert not np.array_equal(rebuilt.output, current.output)
    assert role not in rebuilt.external_cache


def test_shadowed_external_alias_is_not_opened_for_hashing(tmp_path, monkeypatch):
    document, effect = external_document(tmp_path)
    original, _ = audioio.decode(document['source'])
    studio = StudioSession({'Vocal': original}, service.SR)
    document['studio'] = studio.saved_state()
    document['studio']['external_sources']['Vocal'] = str(effect)
    file_hash = service.file_hash

    def unreadable_alias(path, cancel=None):
        if Path(path) == effect:
            raise PermissionError('Shadowed external file is locked')
        return file_hash(path, cancel)

    monkeypatch.setattr(service, 'file_hash', unreadable_alias)
    current = service.prepare(document, Event(), lambda *_: None)
    rebuilt = service.prepare(document, Event(), lambda *_: None, current)
    np.testing.assert_array_equal(rebuilt.output, current.output)
    assert 'external/Vocal' not in rebuilt.media_hashes


def test_new_external_reference_is_loaded_without_old_cache_entry(tmp_path):
    document, effect = external_document(tmp_path)
    plain = deepcopy(document)
    plain['studio'] = None
    current = service.prepare(plain, Event(), lambda *_: None)
    rebuilt = service.prepare(document, Event(), lambda *_: None, current)
    assert rebuilt.external_cache['effect/one'][1].shape == current.original.shape
    assert rebuilt.media_hashes['external/effect/one'] == service.file_hash(effect)
    assert Path(rebuilt.document['studio']['external_sources']['effect/one']) == effect
