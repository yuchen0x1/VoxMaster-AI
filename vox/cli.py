"""Offline batch interface. No QApplication, listening device or network required."""
import argparse
import json
import multiprocessing
import os
from pathlib import Path
import sys
import threading
import unicodedata

from . import __version__, audioio, service
from .presets import PRESETS
from .service import SR, prepare, tuning_plan
from .storage import project, write_json

FORMATS = ('wav', 'flac', 'mp3', 'aac')


def summary(report):
    return {key: report[key] for key in
            ('lufs', 'true_peak_db', 'rms_db', 'classification', 'duration') if key in report}


def _path_key(path):
    # Reserve case and Unicode-normalization aliases before outputs exist.
    # POSIX normcase alone misses case-insensitive macOS volumes.
    return unicodedata.normalize('NFC', os.path.normcase(str(path))).casefold()


def validate_report_path(report, protected, directories=()):
    """Reject report aliases of protected files and paths needed as directories."""
    resolved = report.resolve()
    report_key = _path_key(resolved)
    file_blockers = {report_key, *map(_path_key, resolved.parents)}
    for path in protected:
        other = path.resolve()
        if (_path_key(other) in file_blockers
                or (resolved.exists() and other.exists() and resolved.samefile(other))):
            raise ValueError('报告路径与输入、权重或导出音频冲突：' + str(report))
    for path in directories:
        directory = path.resolve()
        if report_key in {_path_key(directory), *map(_path_key, directory.parents)}:
            raise ValueError('报告路径与所需目录冲突：' + str(report))
    if report.exists() and not report.is_file():
        raise ValueError('报告路径必须是文件：' + str(report))


def add_song_arguments(parser):
    parser.add_argument('input', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--style', choices=list(PRESETS), default='经典喊麦', help='人声风格（默认：经典喊麦）')
    parser.add_argument('--target', choices=('natural', 'forward', 'impact', 'clear', 'full'),
                        default='natural', help='混音目标（默认：natural）')
    parser.add_argument('--master', choices=('conservative', 'standard', 'strong'),
                        default='conservative', help='母带强度（默认：conservative）')
    parser.add_argument('--format', choices=FORMATS, default='wav', help='导出格式（默认：wav）')
    parser.add_argument('--device', choices=('auto', 'CPU', 'DirectML', 'CUDA'),
                        default='auto', help='推理设备，可回退至 CPU（默认：auto）')
    parser.add_argument('--weights', type=Path, metavar='DIR',
                        help='已有固定版本权重文件夹（默认：现有模型缓存；不下载）')


def song_output(args):
    return args.output_dir / (args.input.stem + ' - 歌曲调音.' + args.format)


def song_weights(args):
    """Return the service override, effective cache, and protected weight paths."""
    from . import models_store

    root = args.weights.expanduser().resolve() if args.weights is not None else None
    cache = root if root is not None else models_store.directory()
    return root, cache, [cache / name for name in models_store.FILES]


def song_model_state(cache):
    """Reserve persistent model settings and download/locking state before work starts."""
    from . import models_store

    base = models_store.app_data()
    return [base / 'model-center.json', base / 'model-config.lock',
            cache / 'model-manager.lock',
            *(cache / (name + '.part') for name in models_store.FILES)]


def _quiet_progress(*_):
    """Reserve stdout for the final JSON object."""


def main(argv=None):
    # The packaged console executable also starts the isolated ONNX worker.
    multiprocessing.freeze_support()
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
    tune.add_argument('--format', choices=FORMATS, default='wav')
    tune.add_argument('--report', type=Path, help='将完整 JSON 结果写入此文件')
    song = commands.add_parser('song', help='使用现有权重分轨、混音与母带处理')
    add_song_arguments(song)
    song.add_argument('--report', type=Path, help='将完整 JSON 结果写入此文件')
    commands.add_parser('styles', help='列出可用风格并退出')
    args = parser.parse_args(argv)
    cancel = threading.Event()
    results = []
    failed = False
    if args.command == 'styles':
        print(json.dumps(dict(version=__version__, styles=list(PRESETS)),
                         ensure_ascii=False))
        return 0
    inputs = args.inputs if args.command == 'tune' else [args.input]
    targets = [
        args.output_dir / (path.stem + ' - 调音.' + args.format)
        if args.command == 'tune' else song_output(args) if args.command == 'song' else None
        for path in inputs
    ]
    protected = inputs + [path for path in targets if path is not None]
    directories = [args.output_dir] if args.command != 'analyze' else []
    try:
        if args.command == 'song':
            root, cache, weights = song_weights(args)
            directories.append(cache)
            protected.extend([*weights, *song_model_state(cache)])
        if args.report is not None:
            validate_report_path(args.report, protected, directories)
            args.report.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError, RuntimeError) as exc:
        print(('报告路径无效：' if args.report is not None else '权重路径无效：') + str(exc),
              file=sys.stderr)
        return 2
    try:
        for path, target in zip(inputs, targets):
            published = {}
            try:
                if target is not None and (target.exists() or target.is_symlink()):
                    raise FileExistsError('目标文件已存在：' + str(target))
                if args.command == 'song':
                    missing = [str(weight) for weight in weights if not weight.is_file()]
                    if missing:
                        raise FileNotFoundError('找不到本地模型权重（不自动下载）：' + ', '.join(missing))
                if target is not None:
                    args.output_dir.mkdir(parents=True, exist_ok=True)
                session = prepare(project(str(path.resolve())), cancel, _quiet_progress)
                item = dict(input=str(path), original=summary(session.analysis))
                if args.command == 'song':
                    rendered = service.separate_project(
                        session, args.output_dir, cancel, _quiet_progress, root=root, mode=args.device,
                        song_options={'style': args.style, 'target': args.target, 'master': args.master},
                    )
                    stems = rendered.document['stems']
                    published = dict(stems=stems, recovery_project=rendered.publication_project)
                    protected.extend(Path(stem) for stem in stems.values())
                    protected.append(Path(rendered.publication_project))
                    if args.report is not None:
                        validate_report_path(args.report, protected, directories)
                    audioio.encode(target, rendered.output, SR, cancel=cancel)
                    item.update(published, output=str(target), measured=rendered.measured,
                                audit=rendered.audit, style=rendered.document['style'])
                    for key in ('song', 'separation'):
                        if key in rendered.document:
                            item[key] = rendered.document[key]
                elif args.command == 'tune':
                    doc = session.document.copy()
                    doc.update(applied=True, style=args.style,
                               params=tuning_plan(session.analysis, args.style))
                    rendered = prepare(doc, cancel, _quiet_progress, session)
                    audioio.encode(target, rendered.output, SR, cancel=cancel)
                    item.update(output=str(target), measured=summary(rendered.measured))
                elif args.report is not None:
                    # Keep the default summary and, with --report, the same JSON in both sinks.
                    item['intelligence'] = session.analysis
                results.append(item)
            except Exception as exc:
                failed = True
                # The pair and its project are independent of master encoding; report
                # how to recover them without claiming a master file was written.
                results.append(dict(input=str(path), error=str(exc), **published))
    except KeyboardInterrupt:
        cancel.set()
        return 130
    payload = dict(version=__version__, results=results)
    try:
        printed = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError) as exc:
        print('JSON 序列化失败：' + str(exc), file=sys.stderr)
        return 2
    print(printed)
    if args.report is not None:
        # Recheck protected paths and publish atomically, preserving an old report on failure.
        try:
            validate_report_path(args.report, protected, directories)
            write_json(args.report, payload)
        except (OSError, ValueError, RuntimeError) as exc:
            print('报告写入失败：' + str(exc), file=sys.stderr)
            return 2
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
