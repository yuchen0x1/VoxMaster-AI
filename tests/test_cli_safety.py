"""Protect recordings and finished audio from CLI report path collisions."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unicodedata

import pytest

from vox import cli, storage

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/fleurs-mandarin.wav'


def run_cli(tmp_path, *args):
    env = dict(os.environ, VOXMASTER_DATA=str(tmp_path / 'data'), PYTHONIOENCODING='utf-8')
    return subprocess.run(
        [sys.executable, str(ROOT / 'app.py'), '--cli', *map(str, args)],
        cwd=ROOT, env=env, capture_output=True, timeout=60,
    )


def recording(tmp_path, name='recording.wav'):
    path = tmp_path / name
    shutil.copyfile(FIXTURE, path)
    return path


def test_report_cannot_replace_input_recording(tmp_path):
    source = recording(tmp_path)
    before = source.read_bytes()
    result = run_cli(tmp_path, 'analyze', source, '--report', source)
    assert result.returncode == 2, result.stderr
    assert source.read_bytes() == before
    assert '报告路径' in result.stderr.decode('utf-8')
    assert b'Traceback' not in result.stderr


def test_report_cannot_replace_planned_render(tmp_path):
    source = recording(tmp_path)
    out = tmp_path / 'outputs'
    result = run_cli(tmp_path, 'tune', source, '--output-dir', out,
                     '--report', out / 'recording - 调音.wav')
    assert result.returncode == 2, result.stderr
    assert not out.exists(), 'The conflict must be detected before rendering starts.'
    assert source.read_bytes() == FIXTURE.read_bytes()


@pytest.mark.parametrize('report_name', ['recording - 调音.WAV', 'RECORDING - 调音.wav'])
def test_report_reserves_case_alias_of_nonexistent_output(tmp_path, report_name):
    source = recording(tmp_path)
    out = tmp_path / 'outputs'
    result = run_cli(tmp_path, 'tune', source, '--output-dir', out,
                     '--report', out / report_name)
    assert result.returncode == 2, result.stderr
    assert not out.exists()
    assert source.read_bytes() == FIXTURE.read_bytes()


def test_report_reserves_unicode_alias_of_nonexistent_output(tmp_path):
    source = recording(tmp_path, 'caf\u00e9.wav')
    out = tmp_path / 'outputs'
    report = out / unicodedata.normalize('NFD', 'caf\u00e9 - 调音.wav')
    result = run_cli(tmp_path, 'tune', source, '--output-dir', out, '--report', report)
    assert result.returncode == 2, result.stderr
    assert not out.exists()
    assert source.read_bytes() == FIXTURE.read_bytes()


def test_report_checks_all_batch_inputs_before_first_render(tmp_path):
    first = recording(tmp_path, 'first.wav')
    second = recording(tmp_path, 'second.wav')
    out = tmp_path / 'outputs'
    result = run_cli(tmp_path, 'tune', first, second, '--output-dir', out, '--report', second)
    assert result.returncode == 2, result.stderr
    assert not out.exists()
    assert first.read_bytes() == second.read_bytes() == FIXTURE.read_bytes()


def test_report_rejects_hard_link_alias(tmp_path):
    source = recording(tmp_path)
    alias = tmp_path / 'report.json'
    os.link(source, alias)
    result = run_cli(tmp_path, 'analyze', source, '--report', alias)
    assert result.returncode == 2, result.stderr
    assert source.read_bytes() == alias.read_bytes() == FIXTURE.read_bytes()


def test_report_rejects_symbolic_link_alias(tmp_path):
    source = recording(tmp_path)
    alias = tmp_path / 'report.json'
    try:
        alias.symlink_to(source)
    except OSError as exc:
        pytest.skip('File symlinks are unavailable: ' + str(exc))
    result = run_cli(tmp_path, 'analyze', source, '--report', alias)
    assert result.returncode == 2, result.stderr
    assert source.read_bytes() == FIXTURE.read_bytes()
    assert alias.is_symlink()


@pytest.mark.skipif(os.name != 'nt', reason='Case-insensitive Windows path alias')
def test_report_rejects_windows_case_alias(tmp_path):
    source = recording(tmp_path)
    result = run_cli(tmp_path, 'analyze', source, '--report', str(source).upper())
    assert result.returncode == 2, result.stderr
    assert source.read_bytes() == FIXTURE.read_bytes()


@pytest.mark.parametrize('directory_report', [True, False])
def test_invalid_report_location_has_clean_diagnostic(tmp_path, directory_report):
    source = recording(tmp_path)
    if directory_report:
        report = tmp_path
    else:
        blocker = tmp_path / 'blocker'
        blocker.write_text('existing file', encoding='utf-8')
        report = blocker / 'report.json'
    result = run_cli(tmp_path, 'analyze', source, '--report', report)
    assert result.returncode == 2
    assert b'Traceback' not in result.stderr
    assert '报告路径' in result.stderr.decode('utf-8')


def test_normal_report_matches_stdout_and_replaces_previous_json(tmp_path):
    source = recording(tmp_path)
    report = tmp_path / 'reports' / 'analysis.json'
    report.parent.mkdir()
    report.write_text('{"old": true}', encoding='utf-8')
    result = run_cli(tmp_path, 'analyze', source, '--report', report, '--overwrite-report')
    assert result.returncode == 0, result.stderr
    assert json.loads(report.read_text('utf-8')) == json.loads(result.stdout)
    assert source.read_bytes() == FIXTURE.read_bytes()


def test_report_publication_failure_keeps_existing_file(tmp_path, monkeypatch, capsys):
    source = recording(tmp_path)
    report = tmp_path / 'analysis.json'
    report.write_bytes(b'{"previous": true}')
    before = set(tmp_path.iterdir())
    monkeypatch.setattr(cli, 'prepare', lambda *a, **kw: SimpleNamespace(analysis={'lufs': -20.0}))

    def fail_replace(*args):
        raise OSError('simulated publication failure')

    monkeypatch.setattr(storage.os, 'replace', fail_replace)
    status = cli.main(['analyze', str(source), '--report', str(report), '--overwrite-report'])
    output = capsys.readouterr()
    assert status == 2
    assert report.read_bytes() == b'{"previous": true}'
    assert set(tmp_path.iterdir()) == before, 'A failed write must not leave a temporary file.'
    assert json.loads(output.out)['results'][0]['original']['lufs'] == -20.0
    assert '报告写入失败' in output.err
