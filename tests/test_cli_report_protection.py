"""Report replacement is opt-in; fault injection never needs models or private audio."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unicodedata

import pytest

from vox import audioio, cli, models_store, storage


@pytest.fixture
def offline(tmp_path, monkeypatch):
    # Sentinel media/weights are only path-safety inputs: no decoder or model opens them.
    source = tmp_path / 'caf\u00e9.wav'
    source.write_bytes(b'preserve input media')
    output = tmp_path / 'outputs'
    weights = tmp_path / 'weights'
    weights.mkdir()
    for name in models_store.FILES:
        (weights / name).write_bytes(b'preserve local weight')
    monkeypatch.setattr(models_store, 'directory', lambda: weights)
    monkeypatch.setattr(models_store, 'app_data', lambda: tmp_path / 'data')
    prepared, encoded = [], []
    report = {'lufs': -20.0, 'true_peak_db': -3.0, 'duration': 1.0}

    def prepare(document, *_args):
        prepared.append(document)
        return SimpleNamespace(document=document, analysis=report, measured=report, output=None)

    def encode(path, *_args, **_kwargs):
        encoded.append(Path(path))
        with Path(path).open('xb') as stream:
            stream.write(b'published master audio')
        return audioio.ExportResult(Path(path))

    folder = output / 'vox-stems-test'
    stems = {name: str(folder / (name + '.wav')) for name in ('Vocal', 'Instrumental')}
    recovery = folder / 'Separated.voxproj'

    def separate(*_args, **_kwargs):
        folder.mkdir(parents=True, exist_ok=True)
        for name, path in stems.items():
            Path(path).write_bytes(('preserve ' + name).encode())
        document = storage.project(source)
        document['stems'] = stems.copy()
        storage.save_project(recovery, document, False)
        return SimpleNamespace(document=document, output=None, measured=report,
                               audit={'warnings': []}, publication_project=str(recovery))

    monkeypatch.setattr(cli, 'prepare', prepare)
    monkeypatch.setattr(cli, 'tuning_plan', lambda *_: {})
    monkeypatch.setattr(audioio, 'encode', encode)
    monkeypatch.setattr(cli.service, 'separate_project', separate)
    return SimpleNamespace(source=source, output=output, weights=weights, stems=stems,
                           recovery=recovery, prepared=prepared, encoded=encoded,
                           separate=separate, encode=encode)


def arguments(command, offline, report, overwrite=False):
    result = [command, str(offline.source)]
    if command != 'analyze':
        result += ['--output-dir', str(offline.output)]
    result += ['--report', str(report)]
    if overwrite:
        result.append('--overwrite-report')
    return result


def snapshot(root):
    return {path.relative_to(root): path.read_bytes() if path.is_file() else None
            for path in root.rglob('*')}


def alias(source, destination, kind):
    if kind == 'hardlink':
        os.link(source, destination)
    else:
        try:
            destination.symlink_to(source)
        except OSError as exc:
            pytest.skip('File symlinks are unavailable: ' + str(exc))


@pytest.mark.parametrize('command', ['analyze', 'tune', 'song'])
def test_existing_unrelated_report_is_rejected_before_processing(
        tmp_path, offline, capsys, command):
    report = tmp_path / 'unrelated.dat'
    report.write_bytes(b'not a report; keep these bytes')
    before = snapshot(tmp_path)
    assert cli.main(arguments(command, offline, report)) == 2
    captured = capsys.readouterr()
    assert not captured.out and '--overwrite-report' in captured.err
    assert not offline.prepared and not offline.encoded
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('command', ['analyze', 'tune', 'song'])
@pytest.mark.parametrize('overwrite', [False, True], ids=['new-report', 'explicit-replacement'])
def test_report_matches_stdout_with_explicit_replacement_policy(
        tmp_path, offline, capsys, command, overwrite):
    report = tmp_path / 'reports' / 'result.json'
    if overwrite:
        report.parent.mkdir()
        report.write_bytes(b'previous unrelated contents')
    assert cli.main(arguments(command, offline, report, overwrite)) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(report.read_text('utf-8')) == json.loads(captured.out)
    assert offline.source.read_bytes() == b'preserve input media'
    assert not list(report.parent.glob('.vox-report-*'))
    if command == 'song':
        item, = json.loads(captured.out)['results']
        assert item['stems'] == offline.stems
        assert item['recovery_project'] == str(offline.recovery)


@pytest.mark.parametrize('command', ['analyze', 'tune', 'song'])
@pytest.mark.parametrize('kind', ['direct', 'hardlink', 'symlink'])
def test_overwrite_flag_does_not_allow_input_aliases(
        tmp_path, offline, capsys, command, kind):
    report = offline.source if kind == 'direct' else tmp_path / 'report.json'
    if kind != 'direct':
        alias(offline.source, report, kind)
    before = snapshot(tmp_path)
    assert cli.main(arguments(command, offline, report, True)) == 2
    captured = capsys.readouterr()
    assert not captured.out and '冲突' in captured.err
    assert not offline.prepared and not offline.output.exists()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('command', ['tune', 'song'])
@pytest.mark.parametrize('kind', ['direct', 'case-unicode', 'child', 'directory'])
def test_overwrite_flag_keeps_planned_export_and_directory_reservations(
        tmp_path, offline, capsys, command, kind):
    name = offline.source.stem + (' - 调音.wav' if command == 'tune' else ' - 歌曲调音.wav')
    target = offline.output / name
    report = {'direct': target,
              'case-unicode': offline.output / unicodedata.normalize('NFD', name.upper()),
              'child': target / 'report.json',
              'directory': offline.output}[kind]
    before = snapshot(tmp_path)
    assert cli.main(arguments(command, offline, report, True)) == 2
    captured = capsys.readouterr()
    assert not captured.out and '冲突' in captured.err
    assert not offline.prepared and not offline.output.exists()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('explicit_weights', [False, True], ids=['cache', 'weights-override'])
@pytest.mark.parametrize('index', range(7), ids=[
    'weight-vocal', 'weight-music', 'config', 'config-lock', 'manager-lock',
    'weight-vocal-part', 'weight-music-part',
])
def test_overwrite_flag_keeps_weights_and_persistent_model_state_protected(
        tmp_path, offline, capsys, explicit_weights, index):
    protected = [*(offline.weights / name for name in models_store.FILES),
                 *cli.song_model_state(offline.weights)]
    report = protected[index]
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(b'preserve protected model state')
    before = snapshot(tmp_path)
    argv = arguments('song', offline, report, True)
    if explicit_weights:
        argv += ['--weights', str(offline.weights)]
    assert cli.main(argv) == 2
    captured = capsys.readouterr()
    assert not captured.out and '冲突' in captured.err
    assert not offline.prepared and not offline.output.exists()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('overwrite', [False, True])
@pytest.mark.parametrize('name', ['Vocal', 'Instrumental', 'recovery'])
@pytest.mark.parametrize('kind', ['direct', 'hardlink', 'symlink'])
def test_newly_published_stems_and_recovery_never_become_reports(
        tmp_path, offline, monkeypatch, capsys, overwrite, name, kind):
    protected = offline.recovery if name == 'recovery' else Path(offline.stems[name])
    report = protected if kind == 'direct' else tmp_path / 'report.json'

    def separate(*args, **kwargs):
        result = offline.separate(*args, **kwargs)
        if kind != 'direct':
            alias(protected, report, kind)
        return result

    monkeypatch.setattr(cli.service, 'separate_project', separate)
    assert cli.main(arguments('song', offline, report, overwrite)) == 2
    captured = capsys.readouterr()
    item, = json.loads(captured.out)['results']
    assert item['stems'] == offline.stems
    assert item['recovery_project'] == str(offline.recovery)
    assert '冲突' in item['error'] and '报告写入失败' in captured.err
    assert not offline.encoded and 'output' not in item
    assert storage.load_project(offline.recovery)['stems'] == offline.stems
    for role, path in offline.stems.items():
        assert Path(path).read_bytes() == ('preserve ' + role).encode()
    assert not list(report.parent.glob('.vox-report-*'))


def test_master_encoding_failure_reports_recoverable_publication(
        tmp_path, offline, monkeypatch, capsys):
    def fail(*_args, **_kwargs):
        raise OSError('injected master publication failure')

    monkeypatch.setattr(audioio, 'encode', fail)
    report = tmp_path / 'report.json'
    assert cli.main(arguments('song', offline, report)) == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload == json.loads(report.read_text('utf-8'))
    assert payload['results'] == [dict(input=str(offline.source),
                                       error='injected master publication failure',
                                       stems=offline.stems,
                                       recovery_project=str(offline.recovery))]
    assert storage.load_project(offline.recovery)['stems'] == offline.stems
    assert not offline.encoded


def test_song_keeps_master_cleanup_warning_and_recovery_receipt(
        tmp_path, offline, monkeypatch, capsys):
    def encode(*args, **kwargs):
        result = offline.encode(*args, **kwargs)
        return audioio.ExportResult(result.path, warning='injected post-commit cleanup warning')

    monkeypatch.setattr(audioio, 'encode', encode)
    report = tmp_path / 'report.json'
    assert cli.main(arguments('song', offline, report)) == 0
    item, = json.loads(capsys.readouterr().out)['results']
    assert item['warnings'] == ['injected post-commit cleanup warning']
    assert item['recovery_project'] == str(offline.recovery)
    assert item['stems'] == offline.stems and Path(item['output']).is_file()


@pytest.mark.parametrize('overwrite', [False, True])
def test_final_publication_failure_cleans_staging_and_preserves_previous_report(
        tmp_path, offline, monkeypatch, capsys, overwrite):
    report = tmp_path / 'report.json'
    if overwrite:
        report.write_bytes(b'preserve previous report')
    before = snapshot(tmp_path)
    operation = 'replace' if overwrite else 'rename' if os.name == 'nt' else 'link'
    real_publish = getattr(cli.os, operation)

    def fail(source, destination, *args, **kwargs):
        if Path(destination) == report:
            raise PermissionError('injected final publication failure')
        return real_publish(source, destination, *args, **kwargs)

    monkeypatch.setattr(cli.os, operation, fail)
    assert cli.main(arguments('analyze', offline, report, overwrite)) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)['results'][0]['original']['lufs'] == -20.0
    assert '报告写入失败' in captured.err and 'injected final' in captured.err
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('kind', ['file', 'directory', 'hardlink', 'symlink'])
def test_default_publication_loses_race_without_clobbering_the_winner(
        tmp_path, offline, monkeypatch, capsys, kind):
    report = tmp_path / 'report.json'
    operation = 'rename' if os.name == 'nt' else 'link'
    real_publish = getattr(cli.os, operation)
    raced = []

    def publish(source, destination, *args, **kwargs):
        if Path(destination) == report:
            # This runs after the final validator, immediately at the OS publication boundary.
            assert not report.exists()
            if kind == 'file':
                report.write_bytes(b'concurrent unrelated file')
            elif kind == 'directory':
                report.mkdir()
            else:
                alias(offline.source, report, kind)
            raced.append(True)
        return real_publish(source, destination, *args, **kwargs)

    monkeypatch.setattr(cli.os, operation, publish)
    assert cli.main(arguments('analyze', offline, report)) == 2
    captured = capsys.readouterr()
    assert raced == [True] and '报告写入失败' in captured.err
    assert offline.source.read_bytes() == b'preserve input media'
    if kind == 'file':
        assert report.read_bytes() == b'concurrent unrelated file'
    elif kind == 'directory':
        assert report.is_dir() and not list(report.iterdir())
    else:
        assert report.samefile(offline.source)
    assert not list(tmp_path.glob('.vox-report-*'))


@pytest.mark.parametrize('kind', ['hardlink', 'symlink'])
def test_explicit_overwrite_rechecks_protected_alias_after_staging(
        tmp_path, offline, monkeypatch, capsys, kind):
    report = tmp_path / 'report.json'
    report.write_bytes(b'previous unrelated report')
    real_write = cli.write_json

    def write_then_relink(path, payload):
        real_write(path, payload)
        report.unlink()
        alias(offline.source, report, kind)

    monkeypatch.setattr(cli, 'write_json', write_then_relink)
    assert cli.main(arguments('analyze', offline, report, True)) == 2
    captured = capsys.readouterr()
    assert '报告写入失败' in captured.err and '冲突' in captured.err
    assert report.samefile(offline.source)
    assert offline.source.read_bytes() == b'preserve input media'
    assert not list(tmp_path.glob('.vox-report-*'))


@pytest.mark.parametrize('failure', ['fsync', 'size-limit'])
def test_staging_failure_never_replaces_an_explicitly_selected_report(
        tmp_path, offline, monkeypatch, capsys, failure):
    report = tmp_path / 'report.json'
    report.write_bytes(b'preserve previous report')
    before = snapshot(tmp_path)
    if failure == 'fsync':
        def fail(_fd):
            raise OSError('injected staging fsync failure')
        monkeypatch.setattr(storage.os, 'fsync', fail)
    else:
        monkeypatch.setattr(storage, 'size_limit', lambda _: 8)
    assert cli.main(arguments('analyze', offline, report, True)) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)['results'][0]['original']['lufs'] == -20.0
    assert '报告写入失败' in captured.err
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('overwrite', [False, True])
def test_report_symlink_never_modifies_its_unrelated_target(
        tmp_path, offline, monkeypatch, capsys, overwrite):
    target, report = tmp_path / 'unrelated.dat', tmp_path / 'report.json'
    target.write_bytes(b'preserve symlink target')
    alias(target, report, 'symlink')
    assert cli.main(arguments('analyze', offline, report, overwrite)) == (0 if overwrite else 2)
    captured = capsys.readouterr()
    assert target.read_bytes() == b'preserve symlink target'
    if overwrite:
        assert not report.is_symlink()
        assert json.loads(report.read_text('utf-8')) == json.loads(captured.out)
    else:
        assert report.is_symlink() and not offline.prepared
