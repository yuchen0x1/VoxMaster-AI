"""Offline batch interface. No QApplication, listening device or network required."""
import argparse
import json
from pathlib import Path
import sys
import threading

from . import __version__, audioio
from .presets import PRESETS
from .service import SR, prepare, tuning_plan
from .storage import project


def summary(report):
    return {key: report[key] for key in
            ('lufs', 'true_peak_db', 'rms_db', 'classification', 'duration') if key in report}


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='VoxMaster AI 离线分析与批量调音')
    parser.add_argument('--version', action='version', version=__version__)
    commands = parser.add_subparsers(dest='command', required=True)
    analyze = commands.add_parser('analyze', help='读取音频，输出 JSON 测量')
    analyze.add_argument('input', type=Path)
    tune = commands.add_parser('tune', help='逐个调音，保留已有文件')
    tune.add_argument('inputs', nargs='+', type=Path)
    tune.add_argument('--output-dir', type=Path, required=True)
    tune.add_argument('--style', choices=list(PRESETS), default='经典喊麦')
    tune.add_argument('--format', choices=['wav', 'flac', 'mp3', 'aac'], default='wav')
    args = parser.parse_args(argv)
    cancel = threading.Event()
    results = []
    failed = False
    try:
        for path in ([args.input] if args.command == 'analyze' else args.inputs):
            try:
                # Resolve every output and reject existing files before rendering.
                target = None
                if args.command == 'tune':
                    args.output_dir.mkdir(parents=True, exist_ok=True)
                    target = args.output_dir / (path.stem + ' - 调音.' + args.format)
                    if target.exists():
                        raise FileExistsError('目标文件已存在：' + str(target))
                session = prepare(project(str(path.resolve())), cancel, lambda *a: None)
                item = dict(input=str(path), original=summary(session.analysis))
                if target is not None:
                    doc = session.document.copy()
                    doc.update(applied=True, style=args.style,
                               params=tuning_plan(session.analysis, args.style))
                    rendered = prepare(doc, cancel, lambda *a: None, session)
                    audioio.encode(target, rendered.output, SR, cancel=cancel)
                    item.update(output=str(target), measured=summary(rendered.measured))
                results.append(item)
            except Exception as exc:
                failed = True
                results.append(dict(input=str(path), error=str(exc)))
    except KeyboardInterrupt:
        cancel.set()
        return 130
    print(json.dumps(dict(version=__version__, results=results), ensure_ascii=False, allow_nan=False))
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
