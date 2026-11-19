"""Offline batch interface. No QApplication, listening device or network required."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import unicodedata

from . import __version__, audioio
from .presets import PRESETS
from .service import SR, prepare, tuning_plan
from .storage import project, write_json


def summary(report):
    return {key: report[key] for key in
            ('lufs', 'true_peak_db', 'rms_db', 'classification', 'duration') if key in report}


def validate_report_path(report, protected):
    """Reject report aliases of any input or planned audio output before work starts."""
    resolved = report.resolve()
    # Reserve case and Unicode-normalization aliases before outputs exist.
    # POSIX normcase alone misses case-insensitive macOS volumes.
    report_key = unicodedata.normalize('NFC', os.path.normcase(str(resolved))).casefold()
    for path in protected:
        other = path.resolve()
        other_key = unicodedata.normalize('NFC', os.path.normcase(str(other))).casefold()
        same = report_key == other_key
        if not same and resolved.exists() and other.exists():
            same = resolved.samefile(other)
        if same:
            raise ValueError('报告路径不可与输入音频或导出音频相同：' + str(report))
    if report.exists() and not report.is_file():
        raise ValueError('报告路径必须是文件：' + str(report))
    report.parent.mkdir(parents=True, exist_ok=True)


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='VoxMaster AI 离线分析与批量调音')
    parser.add_argument('--version', action='version', version=__version__)
    commands = parser.add_subparsers(dest='command', required=True)
    analyze = commands.add_parser('analyze', help='读取音频，输出 JSON 测量')
    analyze.add_argument('input', type=Path)
    analyze.add_argument('--report', type=Path, help='将完整 JSON 结果写入此文件')
    tune = commands.add_parser('tune', help='逐个调音，保留已有文件')
    tune.add_argument('inputs', nargs='+', type=Path)
    tune.add_argument('--output-dir', type=Path, required=True)
    tune.add_argument('--style', choices=list(PRESETS), default='经典喊麦')
    tune.add_argument('--format', choices=['wav', 'flac', 'mp3', 'aac'], default='wav')
    tune.add_argument('--report', type=Path, help='将完整 JSON 结果写入此文件')
    commands.add_parser('styles', help='列出可用风格并退出')
    args = parser.parse_args(argv)
    cancel = threading.Event()
    results = []
    failed = False
    if args.command == 'styles':
        print(json.dumps(dict(version=__version__, styles=list(PRESETS)),
                         ensure_ascii=False))
        return 0
    inputs = [args.input] if args.command == 'analyze' else args.inputs
    targets = [
        args.output_dir / (path.stem + ' - 调音.' + args.format)
        if args.command == 'tune' else None
        for path in inputs
    ]
    if args.report is not None:
        try:
            validate_report_path(args.report, inputs + [p for p in targets if p is not None])
        except (OSError, ValueError) as exc:
            print('报告路径无效：' + str(exc), file=sys.stderr)
            return 2
    try:
        for path, target in zip(inputs, targets):
            try:
                # Resolve every output and reject existing files before rendering.
                if target is not None:
                    args.output_dir.mkdir(parents=True, exist_ok=True)
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
    payload = dict(version=__version__, results=results)
    printed = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    print(printed)
    if args.report is not None:
        # Atomic publication preserves an existing report if writing fails.
        try:
            write_json(args.report, payload)
        except (OSError, ValueError) as exc:
            print('报告写入失败：' + str(exc), file=sys.stderr)
            return 2
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
