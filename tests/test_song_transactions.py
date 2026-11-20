"""Real render/persistence and publication boundary checks for song projects."""
from copy import deepcopy
import os
from pathlib import Path
import struct
from threading import Event

import numpy as np
import pytest

from vox import audioio, service, song
from vox.jobs import Worker
from vox.storage import project, load_project, save_project
from vox.studio_session import Session as StudioSession

FIXTURE = Path(__file__).parent / 'fixtures/fleurs-mandarin.wav'


def paired_document(tmp_path, short_vocal=False):
    vocal, _ = audioio.decode(FIXTURE)
    vocal = vocal[2 * service.SR:4 * service.SR] * np.float32(2)
    t = np.arange(len(vocal)) / service.SR
    music = (0.1 * np.column_stack((np.sin(2 * np.pi * 220 * t),
                                   np.sin(2 * np.pi * 330 * t)))).astype(np.float32)
    for name, data in [('source', vocal + music),
                       ('Vocal', vocal[:service.SR] if short_vocal else vocal),
                       ('Instrumental', music)]:
        audioio.encode(tmp_path / (name + '.wav'), data, service.SR, 32)
    document = project(tmp_path / 'source.wav')
    document['stems'] = {role: str(tmp_path / (role + '.wav')) for role in ('Vocal', 'Instrumental')}
    return document


def test_provenance_invalidates_same_size_same_mtime_replaced_stem(tmp_path):
    doc = paired_document(tmp_path)
    doc['separation'] = dict(status='verified', providers=['CPUExecutionProvider'],
                            reconstruction={'length_match': True}, media_sha256={
        'original': service.file_hash(doc['source']), **{
            'stem/' + role: service.file_hash(path) for role, path in doc['stems'].items()
        }})
    current = service.prepare(doc, Event(), lambda *_: None)
    vocal = Path(doc['stems']['Vocal'])
    before = vocal.stat()
    with vocal.open('r+b') as stream:
        stream.seek(-8, 2)
        stream.write(struct.pack('<ff', 0.09, 0.11))
    os.utime(vocal, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert vocal.stat().st_size == before.st_size
    assert vocal.stat().st_mtime_ns == before.st_mtime_ns
    with pytest.raises(ValueError, match='已变更'):
        service.plan_song(current, Event(), lambda *_: None)
    changed = service.prepare(doc, Event(), lambda *_: None, current)
    assert changed.document['separation'] == {
        'status': 'unverified', 'reason': 'media_identity_changed_or_missing'}
    assert changed.sources['Vocal'] is not current.sources['Vocal']
    assert changed.audit['warnings'] and doc['separation']['providers'] == ['CPUExecutionProvider']


@pytest.mark.parametrize('applied', [False, True])
def test_prepare_rejects_media_changed_between_hash_and_commit(tmp_path, applied):
    doc = paired_document(tmp_path)
    doc['separation'] = dict(status='verified', media_sha256={
        'original': service.file_hash(doc['source']), **{
            'stem/' + role: service.file_hash(path) for role, path in doc['stems'].items()
        }})
    if applied:
        current = service.prepare(doc, Event(), lambda *_: None)
        doc = service.plan_song(current, Event(), lambda *_: None).document
    vocal = Path(doc['stems']['Vocal'])
    changed = []

    def replace_during_work(fraction, message):
        if not changed and ((applied and fraction >= .92) or (not applied and fraction == .02)):
            before = vocal.stat()
            with vocal.open('r+b') as stream:
                stream.seek(-8, 2)
                stream.write(struct.pack('<ff', 0.07, 0.13))
            os.utime(vocal, ns=(before.st_atime_ns, before.st_mtime_ns))
            changed.append(True)

    with pytest.raises(ValueError, match='处理期间素材已变更'):
        service.prepare(doc, Event(), replace_during_work)
    assert changed
    assert doc['separation']['status'] == 'verified'


def test_legacy_aligned_external_stems_keep_unequal_tail(tmp_path):
    current = service.prepare(paired_document(tmp_path, short_vocal=True), Event(), lambda *_: None)
    wet = service.plan_song(current, Event(), lambda *_: None)
    assert len(wet.output) == len(current.sources['Instrumental'])
    assert len(wet.sources['Vocal']) < len(wet.sources['Instrumental'])
    assert any('较长轨尾部' in warning for warning in wet.audit['output_warnings'])
    assert np.any(wet.output[-service.SR // 2:] != 0)


def test_non_neutral_studio_edit_replays_processed_stems_and_masters_once(tmp_path, monkeypatch):
    current = service.prepare(paired_document(tmp_path), Event(), lambda *_: None)
    progress = []
    wet = service.plan_song(current, Event(), lambda f, _: progress.append(f), plan={
        'target': 'custom', 'master': 'standard', 'vocal_gain_db': 1.5,
        'instrumental_gain_db': -2, 'instrumental_mid_db': -1.2, 'ceiling_db': -2,
    })
    assert progress == sorted(progress)
    timeline = StudioSession(wet.mix_sources, service.SR)
    timeline.set_param('Vocal', 'gain', -1.5)
    timeline.set_param('Instrumental', 'pan', .2)
    timeline.fade('Vocal', 0, service.SR // 2, True)
    expected_bus = timeline.render(cancel=Event())
    expected = song.master_mix(expected_bus, service.SR, wet.document['song'], Event())
    doc = deepcopy(wet.document)
    doc['studio'] = timeline.saved_state()
    original_master = song.master_mix
    calls = []

    def master(audio, sr, plan, cancel=None):
        calls.append(audio.copy())
        return original_master(audio, sr, plan, cancel)

    monkeypatch.setattr(song, 'master_mix', master)
    progress.clear()
    edited = service.prepare(doc, Event(), lambda f, _: progress.append(f), wet)
    assert len(calls) == 1 and progress == sorted(progress)
    np.testing.assert_array_equal(calls[0], expected_bus)
    np.testing.assert_array_equal(edited.output, expected)
    assert 'master' not in edited.audit['stages']
    path = tmp_path / 'edited.voxproj'
    save_project(path, edited.document)
    recalled = service.prepare(load_project(path), Event(), lambda *_: None)
    assert len(calls) == 2
    np.testing.assert_array_equal(recalled.output, edited.output)


def cached_weights():
    from vox import models_store
    configured = os.getenv('VOX_MODEL_TEST_WEIGHTS')
    root = Path(configured) if configured else models_store.directory()
    try:
        models_store.verify(root)
    except (OSError, ValueError) as exc:
        pytest.skip(f'Local fixed model weights required: {exc}')
    return root


@pytest.mark.parametrize('late', [False, True])
def test_real_separation_cancel_before_vs_after_publication(tmp_path, late):
    weights = cached_weights()
    original = service.prepare(project(FIXTURE), Event(), lambda *_: None)
    output = tmp_path / 'stems'
    output.mkdir()
    successes, cancellations, errors, progress = [], [], [], []

    def work(cancel, ignored):
        def report(fraction, message):
            progress.append(fraction)
            if (late and fraction == 1.0) or (not late and fraction >= .65):
                cancel.set()
        return service.separate_project(original, output, cancel, report, root=weights, mode='CPU')

    worker = Worker(work)
    worker.succeeded.connect(successes.append)
    worker.cancelled.connect(lambda: cancellations.append(True))
    worker.failed.connect(errors.append)
    worker.run()
    assert not errors and progress == sorted(progress)
    if late:
        assert not cancellations and len(successes) == 1
        result = successes[0]
        assert result.publication_committed
        assert result.document['separation']['status'] == 'verified'
        assert result.document['separation']['media_sha256'] == result.media_hashes
        assert all(Path(path).is_file() for path in result.document['stems'].values())
        assert Path(result.publication_project).is_file()
        recovered = load_project(result.publication_project)
        assert recovered['stems'] == result.document['stems']
        assert recovered['separation'] == result.document['separation']
        assert len(list(output.iterdir())) == 1
    else:
        assert cancellations == [True] and not successes
        assert not list(output.iterdir())
    assert original.document['stems'] == {} and original.output is None


def test_published_project_recovers_same_drive_source_reference_and_stems(tmp_path):
    source_folder = tmp_path / 'sources'
    source_folder.mkdir()
    doc = paired_document(source_folder)
    reference = source_folder / 'reference.wav'
    reference.write_bytes(Path(doc['source']).read_bytes())
    doc['reference'] = str(reference)
    current = service.prepare(doc, Event(), lambda *_: None)
    output = tmp_path / 'published'
    output.mkdir()
    result = service.separate_project(
        current, output, Event(), lambda *_: None, root=cached_weights(), mode='CPU',
        song_options={'target': 'natural', 'master': 'conservative'},
    )
    recovered = load_project(result.publication_project)
    assert recovered['source'] == doc['source']
    assert recovered['reference'] == doc['reference']
    assert recovered['stems'] == result.document['stems']
    replay = service.prepare(recovered, Event(), lambda *_: None)
    np.testing.assert_array_equal(replay.output, result.output)
    assert replay.document['separation']['status'] == 'verified'


def test_recovery_project_failure_prevents_separation_publication(tmp_path, monkeypatch):
    from vox import storage

    original = service.prepare(project(FIXTURE), Event(), lambda *_: None)
    output = tmp_path / 'stems'
    output.mkdir()

    def disk_full(*args, **kwargs):
        raise OSError('No space left for publication project')

    monkeypatch.setattr(storage, 'save_project', disk_full)
    with pytest.raises(OSError, match='publication project'):
        service.separate_project(original, output, Event(), lambda *_: None,
                                 root=cached_weights(), mode='CPU')
    assert not list(output.iterdir())
    assert original.document['stems'] == {}
