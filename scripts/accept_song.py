"""Run the offline song CLI and record local, objective audio evidence (no listening test)."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vox import audioio, cli, intelligence


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def audio_spec(metadata):
    return {key: metadata[key] for key in
            ('sample_rate', 'channels', 'bit_depth', 'codec', 'format', 'duration')}


def run_song(args, report):
    command = [sys.executable, '-m', 'vox.cli', 'song', str(args.input),
               '--output-dir', str(args.output_dir), '--report', str(report)]
    for name in ('style', 'target', 'master', 'format', 'device', 'weights'):
        value = getattr(args, name)
        if value is not None:
            command.extend(['--' + name, str(value)])
    return subprocess.run(command, cwd=ROOT, capture_output=True,
                          encoding='utf-8', errors='replace',
                          env=dict(os.environ, PYTHONIOENCODING='utf-8'))


def collect(args):
    started = perf_counter()
    evidence = dict(schema_version=1, status='failed', input={'path': str(args.input)},
                    provenance=args.provenance, rights=args.rights,
                    requested={key: getattr(args, key) for key in
                               ('style', 'target', 'master', 'format', 'device')},
                    output_warnings=[])
    before = None
    try:
        before = evidence['input']['sha256'] = sha256(args.input)
        samples, metadata = audioio.decode(args.input)
        evidence['input']['spec'] = audio_spec(metadata)
        del samples
        with tempfile.TemporaryDirectory(prefix='vox-song-evidence-') as temporary:
            report = Path(temporary) / 'song.json'
            cli_started = perf_counter()
            completed = run_song(args, report)
            evidence['cli_elapsed_seconds'] = round(perf_counter() - cli_started, 3)
            evidence['cli_exit_code'] = completed.returncode
            if completed.stderr.strip():
                evidence['cli_stderr'] = completed.stderr.strip()
            if completed.stdout.strip():
                evidence['cli'] = json.loads(completed.stdout)
            if completed.returncode:
                raise ValueError(f'Song CLI exited with status {completed.returncode}; see CLI evidence.')
            if evidence.get('cli') != json.loads(report.read_text(encoding='utf-8')):
                raise ValueError('CLI stdout does not match its JSON report.')

        item, = evidence['cli']['results']
        output = Path(item['output']).resolve(strict=True)
        if output != cli.song_output(args).resolve() or output.samefile(args.input):
            raise ValueError('CLI returned an unexpected output path.')
        warnings = evidence['output_warnings']
        warnings.extend(item['audit'].get('output_warnings', []))
        samples, metadata = audioio.decode(output)
        meters = intelligence.metrics(samples, audioio.WORK_RATE)
        evidence['output'] = dict(path=str(output), sha256=sha256(output),
                                  spec=audio_spec(metadata), decoded_meters=meters)
        if (metadata['channels'], metadata['sample_rate']) != (2, audioio.WORK_RATE):
            warnings.append('Encoded output is not 44.1 kHz stereo.')
        if abs(metadata['duration'] - evidence['input']['spec']['duration']) > 0.1:
            warnings.append('Decoded output and input durations differ by more than 100 ms.')
        if meters['clipped_samples'] or meters['true_peak_db'] >= 0:
            warnings.append('Decoded output has clipped samples or a true peak at/above 0 dBTP.')
        plan = item.get('song', {})
        if 'ceiling_db' in plan and meters['true_peak_db'] > plan['ceiling_db'] + 0.05:
            warnings.append('Decoded output exceeds the rendered plan ceiling by more than 0.05 dB.')
        evidence['status'] = 'completed'
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        evidence['error'] = str(exc)
    finally:
        if before is not None:
            try:
                after = sha256(args.input)
            except OSError:
                after = None
            evidence['input']['sha256_after'] = after
            evidence['input_unchanged'] = after == before
            if after != before:
                evidence['status'] = 'failed'
                evidence['output_warnings'].append('Input could not be verified unchanged.')
        evidence['elapsed_seconds'] = round(perf_counter() - started, 3)
    return evidence


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    cli.add_song_arguments(parser)
    parser.add_argument('--provenance', required=True, help='User-supplied source and attribution')
    parser.add_argument('--rights', required=True, help='User-supplied license or authorization')
    parser.add_argument('--evidence', type=Path, help='Also save the JSON at this new path')
    args = parser.parse_args(argv)
    if not args.provenance.strip() or not args.rights.strip():
        parser.error('--provenance and --rights must not be blank')
    args.input = args.input.expanduser().absolute()
    args.output_dir = args.output_dir.expanduser().absolute()
    if args.weights is not None:
        args.weights = args.weights.expanduser().absolute()
    if args.evidence is not None:
        args.evidence = args.evidence.expanduser().absolute()
        try:
            _, cache, weights = cli.song_weights(args)
            cli.validate_report_path(args.evidence,
                                     [args.input, cli.song_output(args), *weights,
                                      *cli.song_model_state(cache)], [args.output_dir, cache])
            if args.evidence.exists() or args.evidence.is_symlink():
                raise FileExistsError(f'Evidence path already exists: {args.evidence}')
        except (OSError, ValueError, RuntimeError) as exc:
            parser.error(str(exc))
    evidence = collect(args)
    body = json.dumps(evidence, indent=2, ensure_ascii=False, allow_nan=False)
    print(body)
    if args.evidence is not None:
        try:
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            with args.evidence.open('x', encoding='utf-8') as stream:
                stream.write(body + '\n')
        except OSError as exc:
            print(f'Cannot write evidence: {exc}', file=sys.stderr)
            return 2
    return 0 if evidence['status'] == 'completed' else 1


if __name__ == '__main__':
    sys.exit(main())
