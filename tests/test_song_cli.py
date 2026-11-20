"""Song CLI path safety and offline integration with a licensed fixture."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unicodedata

import numpy as np
import pytest

from vox import audioio, models_store

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/fleurs-mandarin.wav'
FIXTURE_HASH = 'a72c0b59fdba80850552af7991de07f9f4940846d2d70f0890eeb153c40f164b'
EXPORT_NAME = 'fleurs-mandarin - 歌曲调音.wav'


def run(*args, data=None):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    if data is not None:
        env['VOXMASTER_DATA'] = str(data)
    return subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, env=env,
                          capture_output=True, timeout=180)


def cli(tmp_path, *args):
    return run(ROOT / 'app.py', '--cli', *args, data=tmp_path / 'isolated-data')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@pytest.fixture
def source(tmp_path):
    path = tmp_path / FIXTURE.name
    shutil.copyfile(FIXTURE, path)
    assert digest(path) == FIXTURE_HASH
    return path


@pytest.fixture(scope='module')
def cached_weights():
    pytest.importorskip('onnxruntime')
    configured = os.getenv('VOX_MODEL_TEST_WEIGHTS')
    path = Path(configured) if configured else models_store.directory()
    try:
        models_store.verify(path)
    except (OSError, ValueError) as exc:
        pytest.skip(f'Valid local Spleeter weights are not cached: {exc}')
    return path


@pytest.mark.parametrize('collision', ['input', 'hardlink', 'output', 'output-alias', 'output-child', 'output-dir'])
def test_song_rejects_report_conflicts_before_render(tmp_path, source, collision):
    if collision == 'output-alias':
        renamed = source.with_name('caf\u00e9.wav')
        source.rename(renamed)
        source = renamed
    out = tmp_path / 'outputs'
    if collision == 'hardlink':
        alias = tmp_path / 'report.json'
        try:
            os.link(source, alias)
        except OSError as exc:
            pytest.skip(f'Hard links are unavailable: {exc}')
        report = alias
    else:
        reports = dict(input=source, output=out / EXPORT_NAME, output_dir=out,
                       output_child=out / EXPORT_NAME / 'report.json',
                       output_alias=out / unicodedata.normalize('NFD', 'CAF\u00c9 - 歌曲调音.WAV'))
        report = reports[collision.replace('-', '_')]
    result = cli(tmp_path, 'song', source, '--output-dir', out, '--report', report)
    assert result.returncode == 2, result.stderr
    assert '报告路径' in result.stderr.decode('utf-8')
    assert not out.exists()
    assert digest(source) == FIXTURE_HASH
    if collision == 'hardlink':
        assert digest(report) == FIXTURE_HASH


def test_song_cannot_use_weight_file_as_report(tmp_path, source):
    weights = tmp_path / 'weights'
    weights.mkdir()
    model = weights / 'vocals.onnx'
    model.write_bytes(b'unchanged-contents')
    out = tmp_path / 'outputs'
    result = cli(tmp_path, 'song', source, '--output-dir', out, '--weights', weights,
                 '--report', model)
    assert result.returncode == 2, result.stderr
    assert model.read_bytes() == b'unchanged-contents' and not out.exists()


def _model_state_paths(data, weights):
    return [
        data / 'model-center.json',
        data / 'model-config.lock',
        weights / 'model-manager.lock',
        *(weights / (name + '.part') for name in models_store.FILES),
    ]


def _seed_model_state(data, weights):
    data.mkdir(parents=True)
    weights.mkdir(parents=True)
    paths = _model_state_paths(data, weights)
    for index, path in enumerate(paths):
        path.write_bytes(f'preserve-model-state-{index}'.encode())
    paths[0].write_text('{"mode": "CPU"}', encoding='utf-8')
    return paths


def _tree_snapshot(root):
    return {path.relative_to(root): path.read_bytes() if path.is_file() else None
            for path in root.rglob('*')}


@pytest.mark.parametrize('entrypoint', ['song', 'evidence'])
@pytest.mark.parametrize('explicit_weights', [False, True], ids=['default-cache', 'weights-override'])
@pytest.mark.parametrize('existing_state', [False, True], ids=['absent-state', 'existing-state'])
@pytest.mark.parametrize('state_index', range(5), ids=[
    'model-center-config', 'model-config-lock', 'model-manager-lock',
    'vocals-part', 'accompaniment-part',
])
def test_missing_weights_reject_model_state_report_without_writes(
        tmp_path, source, state_index, existing_state, explicit_weights, entrypoint):
    data = tmp_path / 'isolated-data'
    weights = tmp_path / 'weights' if explicit_weights else data / 'models' / models_store.FOLDER
    paths = _seed_model_state(data, weights) if existing_state else _model_state_paths(data, weights)
    report = paths[state_index]
    out = tmp_path / 'outputs'
    options = ['--output-dir', out]
    if explicit_weights:
        options.extend(['--weights', weights])
    before = _tree_snapshot(tmp_path)
    if entrypoint == 'song':
        result = cli(tmp_path, 'song', source, *options, '--report', report)
    else:
        result = run(
            ROOT / 'scripts/accept_song.py', source, *options,
            '--provenance', 'local test fixture', '--rights', 'test authorization',
            '--evidence', report, data=data,
        )

    assert result.returncode == 2, result.stderr
    assert '冲突' in result.stderr.decode('utf-8')
    assert not result.stdout, 'The collision must be rejected before processing starts.'
    assert _tree_snapshot(tmp_path) == before


def test_song_missing_weights_fail_without_fetch_or_render(tmp_path, source):
    weights = tmp_path / 'absent-weights'
    out, report = tmp_path / 'outputs', tmp_path / 'status.json'
    result = cli(tmp_path, 'song', source, '--output-dir', out, '--weights', weights,
                 '--report', report)
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload == json.loads(report.read_text(encoding='utf-8'))
    assert '不自动下载' in payload['results'][0]['error']
    assert not weights.exists() and not out.exists()
    assert digest(source) == FIXTURE_HASH


def test_song_existing_export_is_not_overwritten(tmp_path, source):
    out = tmp_path / 'outputs'
    out.mkdir()
    existing = out / EXPORT_NAME
    shutil.copyfile(source, existing)
    result = cli(tmp_path, 'song', source, '--output-dir', out)
    assert result.returncode == 1, result.stderr
    assert '已存在' in json.loads(result.stdout)['results'][0]['error']
    assert list(out.iterdir()) == [existing]
    assert digest(existing) == digest(source) == FIXTURE_HASH


def test_real_song_writes_stems_and_mixed_master(tmp_path, source, cached_weights):
    out, report = tmp_path / 'outputs', tmp_path / 'reports' / 'song.json'
    result = cli(tmp_path, 'song', source, '--output-dir', out, '--weights', cached_weights,
                 '--style', '干净录音棚', '--target', 'clear', '--master', 'standard', '--device', 'CPU',
                 '--report', report)
    assert result.returncode == 0, (result.stdout, result.stderr)
    payload = json.loads(result.stdout)
    assert payload == json.loads(report.read_text(encoding='utf-8'))
    item, = payload['results']
    assert item['input'] == str(source)
    assert item['style'] == '干净录音棚'
    assert (item['song']['target'], item['song']['master']) == ('clear', 'standard')
    assert item['separation']['weights_sha256'] == {k: v[1] for k, v in models_store.FILES.items()}
    assert item['separation']['providers'] == ['CPUExecutionProvider']
    assert item['separation']['requested_device'] == 'CPU'
    assert item['audit']['song']['plan'] == item['song']
    assert isinstance(item['audit']['output_warnings'], list)
    assert item['measured']['true_peak_db'] <= item['song']['ceiling_db'] + 0.05

    original, _ = audioio.decode(source)
    assert set(item['stems']) == {'Vocal', 'Instrumental'}
    paths = [Path(path) for path in item['stems'].values()]
    assert paths[0].parent == paths[1].parent
    assert paths[0].parent.parent == out.resolve()
    stems = []
    for path in paths:
        audio, spec = audioio.decode(path)
        assert audio.shape == original.shape and spec['bit_depth'] == 32
        stems.append(audio)
    np.testing.assert_allclose(stems[0] + stems[1], original, atol=2e-6, rtol=0)
    output = Path(item['output'])
    assert output == out / EXPORT_NAME
    rendered, spec = audioio.decode(output)
    assert (spec['sample_rate'], spec['channels'], spec['bit_depth']) == (44100, 2, 24)
    assert rendered.shape == original.shape and not np.allclose(rendered, original)
    assert digest(source) == FIXTURE_HASH


def test_real_local_evidence_reports_hashes_and_encoded_specs(tmp_path, source, cached_weights):
    # Use existing weights explicitly; VOXMASTER_DATA stays isolated from the user profile.
    provenance = 'Google FLEURS cmn_hans_cn test, sample 1906; see tests/fixtures/README.md'
    rights = 'CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)'
    report = tmp_path / 'evidence.json'
    run_args = (ROOT / 'scripts/accept_song.py', source, '--output-dir', tmp_path / 'outputs',
                '--weights', cached_weights,
                '--device', 'CPU', '--format', 'flac', '--provenance', provenance,
                '--rights', rights, '--evidence', report)
    result = run(*run_args)
    assert result.returncode == 0, (result.stdout, result.stderr)
    evidence = json.loads(result.stdout)
    assert evidence == json.loads(report.read_text(encoding='utf-8'))
    assert evidence['status'] == 'completed' and evidence['cli_exit_code'] == 0
    assert evidence['provenance'] == provenance and evidence['rights'] == rights
    assert 0 < evidence['cli_elapsed_seconds'] <= evidence['elapsed_seconds']
    assert evidence['input_unchanged'] and evidence['input']['sha256'] == FIXTURE_HASH
    assert evidence['input']['sha256_after'] == FIXTURE_HASH
    assert evidence['input']['spec']['sample_rate'] == 16000
    assert evidence['input']['spec']['channels'] == 1
    output = evidence['output']
    assert output['sha256'] == digest(Path(output['path']))
    assert (output['spec']['codec'], output['spec']['sample_rate'], output['spec']['channels']) == ('flac', 44100, 2)
    item, = evidence['cli']['results']
    assert item['separation']['providers'] == ['CPUExecutionProvider']
    assert all(warning in evidence['output_warnings'] for warning in item['audit']['output_warnings'])
    before = digest(report)
    repeated = run(*run_args)
    assert repeated.returncode == 2 and digest(report) == before


def test_analyze_report_adds_real_intelligence_without_changing_default_stdout(tmp_path, source):
    plain = cli(tmp_path, 'analyze', source)
    report = tmp_path / 'analysis.json'
    full = cli(tmp_path, 'analyze', source, '--report', report)
    assert plain.returncode == full.returncode == 0, (plain.stderr, full.stderr)
    before, after = json.loads(plain.stdout), json.loads(full.stdout)
    assert after == json.loads(report.read_text(encoding='utf-8'))
    detail = after['results'][0].pop('intelligence')
    assert before == after
    assert detail['source_metadata']['sample_rate'] == 16000
    assert detail['inspection']['stereo_evidence'] == 'duplicated_mono'
    assert detail['segments'] and detail['routing']['mode'] == 'manual'
    assert detail['lufs'] == before['results'][0]['original']['lufs']
