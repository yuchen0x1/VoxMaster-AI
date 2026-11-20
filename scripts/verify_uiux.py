"""Capture the production Qt surfaces offline, with public/locally synthesized audio.

QT_QPA_PLATFORM uses native Windows/macOS Qt, or offscreen on headless Linux.
Rendering always uses Qt widgets and paint events, not desktop automation. Set
QT_SCALE_FACTOR before launch to test a different device pixel ratio. --source-root
selects the vox package under test; this script's repository always owns the fixture.
"""

import argparse
import importlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from threading import Event
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests' / 'fixtures' / 'fleurs-mandarin.wav'
LONG_TITLE = '公开语音调音验证·片段名称与非常长的本地工程标题·Mandarin-FLEURS-长文件名回归检查'


NAMED_DIALOGS = ('ParameterDialog', 'ExportDialog', 'ReportDialog', 'PreviewDialog',
                 'SettingsDialog', 'UpdateDialog', 'ModelDialog', 'SongDialog', 'StudioDialog',
                 'RackDialog', 'BalanceDialog')
CANVAS_SLOTS = {('vox.visual', 'Timeline'): 1, ('vox.visual', 'Spectrum'): 1,
                ('vox.studio_timeline', 'Timeline'): 1, ('vox.dsp_panel', 'EqEditor'): 1,
                ('vox.dsp_panel', 'Trace'): 2, ('vox.pitch_tail_editor', 'PitchCanvas'): 1,
                ('vox.review', 'TracePlot'): 2}


def coverage(pages):
    named = sorted({p['widget'] for p in pages} & set(NAMED_DIALOGS))
    inline = [name for name, prefix in (('projects', 'projects-'), ('reference', 'reference-'),
                                       ('preset-library', 'preset-library-'))
              if any(page['name'].startswith(prefix) and page['widget'] == 'QDialog' for page in pages)]
    canvases = {}
    for (module, name), expected in CANVAS_SLOTS.items():
        observed = max((sum(c['module'] == module and c['class'] == name for c in p['controls'])
                        for p in pages), default=0)
        canvases[module + '.' + name] = {'expected': expected, 'observed': observed}
    return {'named_dialogs': named, 'inline_dialogs': inline,
            'application_surfaces': len(named) + len(inline) + int(any(p['widget'] == 'MainWindow' for p in pages)),
            'menus': [p['name'] for p in pages if p['widget'] == 'QMenu'], 'canvas_slots': canvases,
            'canvas_slot_count': sum(min(row['expected'], row['observed']) for row in canvases.values()),
            'qt_fallback_file_entries': [p['name'] for p in pages if p['widget'] == 'QFileDialog'],
            'qt_input_entries': [p['name'] for p in pages if p['widget'] == 'QInputDialog'],
            'qt_message_entries': [p['name'] for p in pages if p['widget'] == 'QMessageBox']}


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='PNG snapshots and uiux.json')
    parser.add_argument('--source-root', default=ROOT, type=Path,
                        help='Directory containing the vox package to import (default: repository)')
    parser.add_argument('--theme', choices=('dark', 'light'), default='dark')
    parser.add_argument('--width', default=1280, type=int, help='Requested workstation width in DIPs')
    parser.add_argument('--height', default=790, type=int, help='Requested workstation height in DIPs')
    parser.add_argument('--maximized', action='store_true', help='Use Qt showMaximized for the workstation')
    parser.add_argument('--timeout', default=240, type=int, help='Hard run timeout in seconds')
    args = parser.parse_args()
    args.source_root = args.source_root.resolve()
    args.output = args.output.resolve()
    if not (args.source_root / 'vox' / '__init__.py').is_file():
        parser.error('--source-root must contain vox/__init__.py')
    if min(args.width, args.height, args.timeout) <= 0:
        parser.error('--width, --height and --timeout must be positive')
    return args


def write_report(path, report):
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n', 'utf-8')
    temp.replace(path)


def stop_tree(process):
    if process.poll() is not None:
        return
    if sys.platform == 'win32':
        # Terminate our venv launcher, its real interpreter, and native decoder/probe
        # children together; killing only the launcher can leave Qt alive on Windows.
        taskkill = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'taskkill.exe'
        try:
            subprocess.run([str(taskkill), '/F', '/T', '/PID', str(process.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, check=False)
        finally:
            if process.poll() is None:
                process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=8)


def supervise(args):
    """Run a disposable process so a regression in a modal/worker cannot hang CI."""
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = args.output / 'uiux.json'
    write_report(manifest, {'status': 'starting', 'source_root': str(args.source_root),
                            'requested_theme': args.theme, 'requested_maximized': args.maximized,
                            'pages': [], 'errors': []})
    with tempfile.TemporaryDirectory(prefix='vox-uiux-') as temp:
        env = dict(os.environ, VOXMASTER_DATA=temp, _VOX_UIUX_CHILD='1', PYTHONDONTWRITEBYTECODE='1')
        if sys.platform == 'win32':
            env.setdefault('QT_QPA_PLATFORM', 'windows')
        elif sys.platform == 'darwin':
            env.setdefault('QT_QPA_PLATFORM', 'cocoa')
        elif not (env.get('DISPLAY') or env.get('WAYLAND_DISPLAY')):
            env.setdefault('QT_QPA_PLATFORM', 'offscreen')
        env.setdefault('PYTHONFAULTHANDLER', '1')
        env.setdefault('QT_SCALE_FACTOR', '1')
        with subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
                              env=env, start_new_session=sys.platform != 'win32') as child:
            try:
                code = child.wait(timeout=args.timeout)
                message = f'Capture child exited with status {code}.'
            except subprocess.TimeoutExpired:
                stop_tree(child)
                code = 124
                message = f'Capture child exceeded {args.timeout}s and was terminated.'
            except KeyboardInterrupt:
                stop_tree(child)
                code = 130
                message = 'Capture cancelled and the child tree terminated.'
    report = json.loads(manifest.read_text('utf-8'))
    if code and (code == 124 or report.get('status') != 'finished'):
        report['status'] = 'failed'
        report['errors'].append({'stage': 'process', 'message': message})
        write_report(manifest, report)
        print(message, file=sys.stderr)
    return code


def run_capture(args):
    # No project imports above this point. Do not fall back to the current vox tree.
    sys.path.insert(0, str(args.source_root))
    import numpy as np
    import PySide6
    from PySide6.QtCore import (
        QCoreApplication,
        QEvent,
        QPoint,
        QRect,
        Qt,
        QThreadPool,
        QTimer,
        qInstallMessageHandler,
    )
    from PySide6.QtGui import QFont, QPalette
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QAbstractButton,
        QAbstractItemView,
        QAbstractSpinBox,
        QApplication,
        QComboBox,
        QDialog,
        QFileDialog,
        QGroupBox,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QMenu,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QScrollArea,
        QSlider,
        QStyle,
        QStyleOptionComboBox,
        QTabBar,
        QTableView,
        QTabWidget,
        QTextEdit,
        QToolButton,
        QTreeWidget,
        QWidget,
    )

    import vox
    from vox import audioio, service, storage, visual
    from vox.interface import MainWindow
    from vox.platforms import ui_font
    from vox.review import PreviewDialog
    from vox.song_dialog import SongDialog
    from vox.studio import StudioDialog
    from vox.update_dialog import UpdateDialog

    source = Path(vox.__file__).resolve()
    if source.parent != (args.source_root / 'vox').resolve():
        raise RuntimeError(f'Wrong vox source selected: {source}')
    data = Path(os.environ['VOXMASTER_DATA']).resolve()
    if storage.ROOT.resolve() != data:
        raise RuntimeError(f'VOXMASTER_DATA isolation failed: {storage.ROOT}')
    report = {
        'status': 'running', 'source_root': str(args.source_root), 'vox_module': str(source),
        'requested_theme': args.theme, 'requested_size': [args.width, args.height],
        'requested_maximized': args.maximized,
        'qt_scale_factor': os.environ.get('QT_SCALE_FACTOR'), 'pyside': PySide6.__version__,
        'audio_fixture': 'FLEURS Mandarin (CC BY 4.0); synthetic accompaniment and reference',
        'safety': {'isolated_data': True, 'network': False, 'playback': False,
                   'file_dialog': 'Qt non-native fallback; OS-native picker is not evaluated'},
        'pages': [], 'warnings': [], 'errors': [], 'qt_messages': [],
    }
    manifest = args.output / 'uiux.json'
    active = 'initialization'

    def qt_message(kind, context, message):
        row = {'stage': active, 'type': kind.name, 'category': context.category, 'message': message}
        if row not in report['qt_messages']:
            report['qt_messages'].append(row)
            if kind.name in ('QtWarningMsg', 'QtCriticalMsg', 'QtFatalMsg'):
                print(f"Qt {kind.name} [{active}]: {message}", file=sys.stderr)

    old_handler = qInstallMessageHandler(qt_message)
    app = QApplication([])
    app.setApplicationName('VoxMaster AI')
    app.setOrganizationName('VoxMaster')
    app.setQuitOnLastWindowClosed(False)
    if sys.platform != 'darwin':
        app.setStyle('Fusion')
    app.setFont(QFont(ui_font(), 10))
    app.setWindowIcon(visual.app_icon())
    try:
        theme = importlib.import_module('vox.theme')
    except ModuleNotFoundError as exc:
        if exc.name != 'vox.theme':
            raise
        theme = None
    if theme is None:
        app.setStyleSheet(visual.STYLES)
        report['theme_backend'] = 'legacy-STYLES'
        report['theme'] = 'dark'
        if args.theme != 'dark':
            report['warnings'].append('Legacy source has no light mode; captured legacy dark stylesheet.')
    else:
        theme.install_theme(app, args.theme)
        report['theme_backend'] = 'vox.theme'
        report['theme'] = theme.manager().resolved
    report['qt_platform'] = app.platformName()
    report['font_family'] = app.font().family()
    write_report(manifest, report)

    def pump():
        app.processEvents()

    def wait_for(condition, message, seconds=20):
        deadline = time.monotonic() + seconds
        while not condition():
            if time.monotonic() >= deadline:
                raise TimeoutError(message)
            pump()
            time.sleep(.01)
        pump()

    def box(rect):
        return [rect.x(), rect.y(), rect.width(), rect.height()]

    def plain(text):
        return str(text).replace('\u2028', '\n')

    def extent(text, metrics, width=None):
        lines = plain(text).split('\n')
        if width is None:
            return max((metrics.horizontalAdvance(line) for line in lines), default=0), len(lines) * metrics.height()
        bounds = metrics.boundingRect(QRect(0, 0, max(1, width), 100_000),
                                      Qt.TextFlag.TextWordWrap.value | Qt.AlignmentFlag.AlignLeft.value, text)
        return bounds.width(), bounds.height()

    def metrics_check(text, metrics, rect, *, wrap=False, policy='clip'):
        tw, th = extent(text, metrics, rect.width() if wrap else None)
        result = {'available': [rect.width(), rect.height()], 'required': [tw, th], 'status': 'fits'}
        if tw > rect.width() + 1 or th > rect.height() + 1:
            result['status'] = policy
        return result

    def diagnostics(widget):
        controls = []
        not_in_viewport = 0
        types = (QLabel, QAbstractButton, QLineEdit, QComboBox, QAbstractSpinBox, QTabBar, QMenu,
                 QAbstractItemView, QPlainTextEdit, QTextEdit, QGroupBox, QProgressBar, QSlider,
                 QScrollArea)
        for child in [widget, *widget.findChildren(QWidget)]:
            module = type(child).__module__
            if child is not widget and (child.isWindow() or child.window() is not widget.window()):
                continue
            if not child.isVisibleTo(widget) or not (isinstance(child, types) or module.startswith('vox.')):
                continue
            # Spin box editors and Qt internal buttons are represented by their container.
            if isinstance(child, QLineEdit) and isinstance(child.parentWidget(), QAbstractSpinBox):
                continue
            if isinstance(child, QToolButton) and not child.text() and not child.accessibleName():
                continue
            rect = QRect(child.mapToGlobal(QPoint()) - widget.mapToGlobal(QPoint()), child.size())
            visible = rect.intersected(widget.rect())
            ancestor = child.parentWidget() if child is not widget else None
            while ancestor is not None and ancestor is not widget:
                origin = ancestor.mapToGlobal(QPoint()) - widget.mapToGlobal(QPoint())
                visible = visible.intersected(QRect(origin, ancestor.size()))
                ancestor = ancestor.parentWidget()
            if visible.isEmpty():
                not_in_viewport += 1
                continue
            row = {'class': type(child).__name__, 'module': module, 'name': child.objectName(),
                   'accessible_name': child.accessibleName(), 'rect': box(rect),
                   'visible_rect': box(visible), 'enabled': child.isEnabled(),
                   'focused': child.hasFocus()}
            if visible != rect:
                row['partly_outside_viewport'] = True
            text, content = '', child.contentsRect()
            fm = child.fontMetrics()
            if isinstance(child, QLabel):
                text = child.text()
                margin = child.margin() + max(0, child.indent())
                content.adjust(margin, child.margin(), -margin, -child.margin())
                if text:
                    displayed = (text.replace('&&', '\0').replace('&', '').replace('\0', '&')
                                 if child.buddy() is not None else text)
                    if type(child).__name__ == 'ElidedLabel' and module == 'vox.visual':
                        # Production ElidedLabel explicitly paints ElideMiddle and
                        # retains its full text in the tooltip/accessibility metadata.
                        row['painted_text'] = fm.elidedText(displayed, Qt.ElideMiddle, content.width())
                        row['text_clipping'] = metrics_check(displayed, fm, content, policy='intentional_middle_elision')
                    else:
                        row['text_clipping'] = metrics_check(displayed, fm, content, wrap=child.wordWrap())
            elif isinstance(child, QAbstractButton):
                text = child.text().replace('&&', '\0').replace('&', '').replace('\0', '&')
                # The production style's size hint includes focus frame, indicator, and icon.
                natural = child.sizeHint()
                if text:
                    result = metrics_check(text, fm, content)
                    padding = max(0, natural.width() - extent(text, fm)[0])
                    if fm.horizontalAdvance(text) + padding > child.width() + 1 and result['status'] == 'fits':
                        result['status'] = 'style_hint_exceeds_width'
                    row['text_clipping'] = result
                row['checked'] = child.isChecked() if child.isCheckable() else None
                row['pressed'] = child.isDown()
                row['under_mouse'] = child.underMouse()
            elif isinstance(child, QComboBox):
                text = child.currentText()
                option = QStyleOptionComboBox()
                child.initStyleOption(option)
                content = child.style().subControlRect(QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, child)
                if text:
                    row['text_clipping'] = metrics_check(text, fm, content, policy='clip_or_elide')
                row['option_count'] = child.count()
            elif isinstance(child, (QLineEdit, QAbstractSpinBox)):
                text = child.text() or (child.placeholderText() if isinstance(child, QLineEdit) else '')
                editor = child if isinstance(child, QLineEdit) else child.lineEdit()
                m = editor.textMargins()
                content = editor.contentsRect().adjusted(m.left(), m.top(), -m.right(), -m.bottom())
                if text:
                    row['text_clipping'] = metrics_check(text, fm, content, policy='editable_horizontal_scroll')
            elif isinstance(child, (QPlainTextEdit, QTextEdit)):
                text = child.toPlainText()
                row['scrollable_text'] = {'characters': len(text), 'blocks': child.document().blockCount(),
                                          'vertical_overflow': child.verticalScrollBar().maximum() > 0,
                                          'horizontal_overflow': child.horizontalScrollBar().maximum() > 0}
            elif isinstance(child, QTabBar):
                row['tabs'] = [{'text': child.tabText(i), 'rect': box(child.tabRect(i)),
                                'current': i == child.currentIndex(),
                                'text_clipping': metrics_check(child.tabText(i), fm, child.tabRect(i),
                                                               policy='clip_or_elide')}
                               for i in range(child.count())]
            elif isinstance(child, QMenu):
                row['actions'] = [{'text': item.text(), 'rect': box(child.actionGeometry(item)),
                                   'enabled': item.isEnabled()} for item in child.actions() if not item.isSeparator()]
            elif isinstance(child, QAbstractItemView):
                model = child.model()
                if model is not None:
                    parent = child.rootIndex()
                    row['item_rows'] = model.rowCount(parent)
                    entries = []

                    def add_rows(parent_index, depth=0, *, child=child, model=model, fm=fm, entries=entries):
                        if depth > 4:
                            return
                        columns = (1 if isinstance(child, QListWidget) else child.columnCount()
                                   if isinstance(child, QTreeWidget) else model.columnCount(parent_index))
                        for y in range(min(100, model.rowCount(parent_index))):
                            for x in range(min(20, columns)):
                                index = (child.indexFromItem(child.item(y)) if isinstance(child, QListWidget)
                                         else model.index(y, x, parent_index))
                                value = index.data(Qt.DisplayRole)
                                cell = child.visualRect(index)
                                if value is None or not child.viewport().rect().intersects(cell):
                                    continue
                                avail = cell.adjusted(4, 0, -4, 0)
                                entries.append({'text': str(value), 'rect_in_viewport': box(cell),
                                                'text_clipping': metrics_check(str(value), fm, avail,
                                                                               policy='item_elide_or_clip')})
                                if x == 0 and isinstance(child, QTreeWidget) and child.isExpanded(index):
                                    add_rows(index, depth + 1)
                    add_rows(parent)
                    row['visible_items'] = entries
            elif isinstance(child, QGroupBox):
                text = child.title()
            elif isinstance(child, QProgressBar):
                text = child.text() if child.isTextVisible() else ''
                row['value'] = child.value()
            if text:
                row['text'] = plain(text)[:1300]
            if child.toolTip():
                row['tooltip'] = child.toolTip()[:600]
            controls.append(row)
        return controls, not_in_viewport

    def snapshot(key, widget, *, state=None):
        nonlocal active
        active = key
        # Resizing wrapped labels can post a follow-up layout request to the
        # scroll content. Drain a bounded number of event turns before painting.
        for _ in range(3):
            pump()
        pixmap = widget.grab()
        path = args.output / (key + '.png')
        if pixmap.isNull() or not pixmap.save(str(path)):
            raise OSError(f'Could not save Qt screenshot {path}')
        controls, offscreen = diagnostics(widget)
        clipping = [i for i, ctl in enumerate(controls)
                    if ctl.get('text_clipping', {}).get('status') == 'clip']
        tab_names = [tabs.tabText(tabs.currentIndex()) for tabs in widget.findChildren(QTabWidget)
                     if tabs.isVisibleTo(widget)]
        page = {'name': key, 'window_title': widget.windowTitle(), 'state': state, 'tabs': tab_names,
                'widget': type(widget).__name__, 'logical_size': [widget.width(), widget.height()],
                'png': path.name, 'png_size': [pixmap.width(), pixmap.height()],
                'device_pixel_ratio': pixmap.devicePixelRatio(), 'maximized': widget.isMaximized(),
                'theme': theme.manager().resolved if theme else 'dark',
                'palette_window': widget.palette().color(QPalette.Window).name(),
                'controls': controls, 'controls_outside_viewport': offscreen,
                'possible_clipping_control_indices': clipping}
        report['pages'].append(page)
        write_report(manifest, report)
        print(f"{key}: {page['logical_size']} DIP → {page['png_size']} px", flush=True)

    def show(widget):
        if widget.layout():
            widget.layout().activate()
        widget.resize(min(widget.width(), args.width), min(widget.height(), args.height))
        widget.show()
        pump()

    def capture_tabs(dialog, prefix, keys):
        tabs = dialog.findChild(QTabWidget)
        valid_counts = (len(keys) - 1, len(keys)) if prefix == 'settings' else (len(keys),)
        if tabs.count() not in valid_counts:
            raise AssertionError(f'{prefix}: unmapped tab count {tabs.count()}, expected {valid_counts}')
        for i in range(tabs.count()):
            tabs.setCurrentIndex(i)
            pump()
            view = tabs.currentWidget().findChild(QTableView)
            if view is not None and view.model().rowCount():
                view.setCurrentIndex(view.model().index(0, 0))
                view.selectRow(0)
            if prefix == 'parameters' and keys[i] == 'pitch-compression':
                wait_for(lambda: dialog.meters.info.text() and not dialog.meters.info.text().startswith('正在'),
                         'Pitch/compression measurement did not finish')
                if dialog.meters.info.text().startswith('测量失败'):
                    raise AssertionError(dialog.meters.info.text())
            snapshot(f'{prefix}-{keys[i]}', dialog)
            if prefix == 'parameters' and keys[i] == 'controls' and isinstance(tabs.currentWidget(), QScrollArea):
                scroll = tabs.currentWidget().verticalScrollBar()
                scroll.setValue(scroll.maximum())
                snapshot('parameters-controls-scrolled', dialog, state='scrolled to bottom')
                scroll.setValue(0)
        if prefix == 'parameters' and dialog.meters:
            dialog.meters.cancel()
            if not QThreadPool.globalInstance().waitForDone(5000):
                raise TimeoutError('Meter worker did not stop')

    @contextmanager
    def own(dialog):
        try:
            show(dialog)
            yield dialog
        finally:
            dialog.reject()
            if isinstance(dialog, StudioDialog):
                wait_for(lambda: dialog.future is None, 'Studio task did not cancel', 8)
                dialog.executor.shutdown(wait=True, cancel_futures=True)
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            pump()

    def modal(key, launch, inspect=None, *, accepted=False):
        """Intercept a production exec, render the real instance and always reject it."""
        seen = []
        failures = []

        def capture(dialog):
            seen.append(dialog.windowTitle())
            show(dialog)
            try:
                if inspect is None:
                    snapshot(key, dialog)
                else:
                    inspect(dialog)
            except Exception as exc:  # noqa: BLE001 -- retain full evidence and reject every modal
                # Production Studio catches exceptions from exec and opens another
                # modal. Defer capture errors until its production call returns.
                failures.append(exc)
            finally:
                if accepted and not failures:
                    dialog.accept()
                else:
                    dialog.reject()
            return int(QDialog.DialogCode.Accepted if accepted and not failures else QDialog.DialogCode.Rejected)

        with patch.object(QDialog, 'exec', capture):
            launch()
        if failures:
            raise failures[0]
        # The production wrapper calls deleteLater() after its exec returns. Do not
        # synchronously dispatch unrelated timers here; snapshots pump events before
        # every grab and final cleanup drains deferred deletes.
        if len(seen) != 1:
            raise AssertionError(f'{key}: expected one modal, got {seen}')

    def message_box(kind, key, launch):
        def present(parent, title, text, buttons=None, default=None):
            standard = buttons or (QMessageBox.Yes | QMessageBox.No if kind == 'question' else QMessageBox.Ok)
            icon = {'information': QMessageBox.Information, 'question': QMessageBox.Question,
                    'warning': QMessageBox.Warning}[kind]
            message = QMessageBox(icon, title, text, standard, parent)
            if default:
                message.setDefaultButton(default)
            message.setEscapeButton(QMessageBox.No if kind == 'question' else QMessageBox.Ok)
            with own(message):
                snapshot(key, message, state='dismissed without taking action')
            return QMessageBox.No if kind == 'question' else QMessageBox.Ok

        count = len(report['pages'])
        with patch.object(QMessageBox, kind, staticmethod(present)):
            launch()
        if not any(page['name'] == key for page in report['pages'][count:]):
            raise AssertionError(f'{key}: production {kind} call did not create a message box')

    def file_box(method, key, launch):
        def present(parent, caption='', directory='', file_filter='', *unused, **kwargs):
            # Qt's OS-native picker is deliberately not opened or measured here.
            initial = Path(directory) if directory else data
            initial = initial if initial.is_absolute() else data / initial
            folder = initial if initial.is_dir() else initial.parent
            dialog = QFileDialog(parent, caption, str(folder), file_filter)
            dialog.setOption(QFileDialog.DontUseNativeDialog, True)
            if method == 'getSaveFileName':
                dialog.setAcceptMode(QFileDialog.AcceptSave)
                dialog.setFileMode(QFileDialog.AnyFile)
                dialog.selectFile(initial.name)
            elif method == 'getExistingDirectory':
                dialog.setFileMode(QFileDialog.Directory)
                dialog.setOption(QFileDialog.ShowDirsOnly, True)
            else:
                dialog.setFileMode(QFileDialog.ExistingFile)
            with own(dialog):
                snapshot(key, dialog, state='Qt fallback (not OS-native), cancelled')
            return '' if method == 'getExistingDirectory' else ('', '')

        count = len(report['pages'])
        with patch.object(QFileDialog, method, staticmethod(present)):
            launch()
        if not any(page['name'] == key for page in report['pages'][count:]):
            raise AssertionError(f'{key}: production {method} call did not create a file picker')

    def input_box(method, key, launch, *, accept_count=0, answer_override=None):
        captured = []

        def present(parent, title, label_text, *values, **kwargs):
            index = len(captured)
            dialog = QInputDialog(parent)
            dialog.setWindowTitle(title)
            dialog.setLabelText(label_text)
            if method == 'getDouble':
                value, low, high, digits = values
                dialog.setInputMode(QInputDialog.DoubleInput)
                dialog.setDoubleRange(low, high)
                dialog.setDoubleDecimals(digits)
                dialog.setDoubleValue(value)
                answer = value
            elif method == 'getItem':
                items, selected, editable = values
                dialog.setComboBoxItems(items)
                dialog.setComboBoxEditable(editable)
                answer = items[selected]
                dialog.setTextValue(answer)
            else:
                answer = kwargs.get('text', '')
                dialog.setTextValue(answer)
            if answer_override is not None:
                answer = answer_override
                dialog.setTextValue(str(answer))
            with own(dialog):
                snapshot(key if index == 0 else f'{key}-{index + 1}', dialog,
                         state='accepted into isolated UI fixture' if index < accept_count else 'cancelled')
            captured.append(title)
            return answer, index < accept_count

        with patch.object(QInputDialog, method, staticmethod(present)):
            launch()
        if not captured:
            raise AssertionError(f'{key}: production {method} call did not create an input dialog')

    def popup(key, launch):
        captured = []

        def inspect_menu():
            menus = [widget for widget in QApplication.topLevelWidgets()
                     if isinstance(widget, QMenu) and widget.isVisible()]
            if len(menus) != 1:
                raise AssertionError(f'{key}: expected one visible Qt menu, got {len(menus)}')
            menu = menus[0]
            try:
                snapshot(key, menu, state='no action invoked')
                captured.append(menu)
            finally:
                menu.close()

        # A timer closes the real production exec() after capturing its shown QMenu.
        # This renders a native widget without invoking any action or desktop input.
        QTimer.singleShot(0, inspect_menu)
        launch()
        if len(captured) != 1:
            raise AssertionError(f'{key}: expected one Qt menu, got {len(captured)}')

    def click_named(dialog, text):
        button = next((x for x in dialog.findChildren(QAbstractButton) if x.text() == text), None)
        if button is None:
            raise AssertionError(f'Button not found: {text}')
        button.click()

    def button_states(window):
        button = window.go
        if not button.isEnabled():
            raise AssertionError('Primary action was not enabled after fixture load')
        window.activateWindow()
        button.setFocus(Qt.TabFocusReason)
        pump()
        snapshot('workstation-primary-focus', window, state='enabled primary action with keyboard focus')
        position = button.rect().center()
        QTest.mouseMove(button, position)
        # QTest does not synthesize a platform enter/leave on all Qt plugins.
        button.setAttribute(Qt.WA_UnderMouse, True)
        app.sendEvent(button, QEvent(QEvent.Enter))
        try:
            snapshot('workstation-primary-hover', window, state='Qt test hover on the production primary action')
            QTest.mousePress(button, Qt.LeftButton, pos=position)
            if not button.isDown():
                raise AssertionError('Qt test press did not enter the pressed state')
            snapshot('workstation-primary-pressed', window, state='button held; render not dispatched')
        finally:
            # Release outside the hit area so no production command is dispatched.
            QTest.mouseRelease(button, Qt.LeftButton, pos=QPoint(-3, -3))
            button.setAttribute(Qt.WA_UnderMouse, False)
            app.sendEvent(button, QEvent(QEvent.Leave))
        if window.worker is not None:
            window.cancel()
            raise AssertionError('Primary-action state capture unexpectedly started a task')

    def record_error(stage, exc):
        report['errors'].append({'stage': stage, 'message': str(exc), 'traceback': traceback.format_exc()})
        print(f'{stage}: {exc}', file=sys.stderr)
        write_report(manifest, report)

    @contextmanager
    def stage(name):
        nonlocal active
        active = name
        try:
            yield
        except Exception as exc:  # noqa: BLE001 -- one failed surface must not hide unrelated surfaces
            record_error(name, exc)

    def work():
        nonlocal active
        active = 'workstation-init'
        window = MainWindow()
        window.resize(args.width, args.height)
        if args.maximized:
            window.showMaximized()
        else:
            window.show()
        # Recovery, prefs and generated audio never leave this run's disposable tree.
        project_dir = data / '审计夹具'
        project_dir.mkdir()
        window.settings.update(project_dir=str(project_dir), export_dir=str(project_dir))
        try:
            pump()
            with stage('empty workstation and projects'):
                snapshot('workstation-empty', window, state='no project')
                modal('projects-empty', window.projects)
                for mode in ('song', 'multitrack', 'vocal'):
                    window.select_mode(mode)
                    if mode != 'vocal':
                        snapshot(f'workstation-empty-{mode}', window, state='no project')
                file_box('getOpenFileName', 'file-open-audio', window.import_audio)
                file_box('getOpenFileName', 'file-open-project', window.open_project)
                missing_doc = storage.project(project_dir / (LONG_TITLE + '·待重新定位.wav'),
                                              '缺少素材的本地工程')
                missing_project = project_dir / '缺少素材·重新定位.voxproj'
                storage.save_project(missing_project, missing_doc, False)
                file_box('getOpenFileName', 'file-relink-missing-source',
                         lambda: window.open_path(str(missing_project)))
            with stage('hardware'):
                wait_for(lambda: hasattr(window, 'hardware_job') and not window.hardware_job.isRunning(),
                         'Local hardware probe did not finish', 40)
                if window.device_report.get('errors'):
                    report['warnings'].extend(str(text) for text in window.device_report['errors'])

            active = 'real audio decode and prepare'
            cancel = Event()

            def progress(*_):
                pump()

            short_file = project_dir / 'FLEURS 普通话语音.wav'
            long_file = project_dir / (LONG_TITLE + '.wav')
            shutil.copyfile(FIXTURE, short_file)
            shutil.copyfile(FIXTURE, long_file)
            short_doc = storage.project(short_file, 'FLEURS 普通话公开语音')
            dry = service.prepare(short_doc, cancel, progress)
            window.commit(dry, reset=True)
            window.show_ready(dry)
            with stage('loaded workstation and reference empty'):
                window.timeline.region = (.25, min(1.5, len(dry.original) / service.SR))
                window.spectrum.update_audio(dry.original[:4096])
                snapshot('workstation-loaded', window, state='real FLEURS audio, selected region')
                button_states(window)
                window.on_progress(.42, '正在分析 · 离线进度显示检查')
                snapshot('workstation-progress', window, state='production progress callback; local display only')
                window.show_ready(dry)
                modal('reference-empty', window.reference)
                modal('report-dry', window.report_view, lambda d: capture_tabs(
                    d, 'report-dry', ('overview', 'segments', 'before-after')))
                popup('menu-workstation-waveform', lambda: window.wave_menu(QPoint(30, 30)))
                modal('song-no-stems', window.song_mix)
                previous = window.s.document
                window.s.document = deepcopy(previous)
                window.s.document['studio'] = {}
                try:
                    message_box('information', 'song-mix-incompatible-project', window.song_mix)
                finally:
                    window.s.document = previous
                file_box('getExistingDirectory', 'file-separation-output', window.separation_destination)
                message_box('question', 'model-required-confirmation', window.separation_model_ready)
            with stage('workstation error'):
                def missing():
                    window.open_path(str(project_dir / (LONG_TITLE + '·不存在.wav')))
                    wait_for(lambda: window.worker is None, 'Missing source failure did not finish')
                message_box('information', 'error-missing-source', missing)
                snapshot('workstation-error', window, state='failed missing-file import; current audio retained')

            active = 'real audio tune and reference'
            ref = project_dir / '公开夹具·合成参考.wav'
            vocal = dry.original * np.float32(.75)
            t = np.arange(len(vocal), dtype=float) / service.SR
            music = (.027 * np.column_stack((np.sin(2 * np.pi * 110 * t),
                                              np.sin(2 * np.pi * 167 * t)))).astype(np.float32)
            audioio.encode(ref, .7 * vocal + music, service.SR, 24)
            doc = storage.project(long_file, LONG_TITLE)
            doc['reference'] = str(ref)
            measured = service.prepare(doc, cancel, progress)
            params = service.tuning_plan(measured.analysis, reference=measured.reference_report)
            if not params.get('automation'):
                raise AssertionError('Public fixture did not yield production automation parameters')
            doc.update(applied=True, params=params, history=['离线 UI 验证 · 使用公开语音与合成参考'])
            wet = service.prepare(doc, cancel, progress, measured)
            if wet.output is None:
                raise AssertionError('Vocal render did not create audio')
            report['audio_measurements'] = {'dry_lufs': round(float(dry.analysis['lufs']), 3),
                                             'wet_lufs': round(float(wet.measured['lufs']), 3),
                                             'segments': len(wet.analysis['segments'])}
            report['warnings'].extend(window.render_warnings(wet))
            project = project_dir / (LONG_TITLE + '.voxproj')
            storage.save_project(project, wet.document, False)
            window.commit(wet, reset=True, path=project)
            window.show_ready(wet)
            window.timeline.region = (.3, 1.75)
            window.spectrum.update_audio(wet.output[:4096])
            snapshot('workstation-long-name-rendered', window, state='A/B ready; long project and source names')
            with stage('projects and presets library'):
                modal('projects-loaded', window.projects)
                window.custom[LONG_TITLE] = deepcopy(params)
                window.style.addItem(LONG_TITLE)
                window.style.setCurrentText(LONG_TITLE)

                def library(dialog):
                    snapshot('preset-library-long-name', dialog, state='selected long custom preset')
                    message_box('question', 'preset-overwrite-confirmation', lambda: input_box(
                        'getText', 'input-preset-name', lambda: click_named(dialog, '复制为我的风格'),
                        accept_count=1, answer_override=LONG_TITLE))
                    input_box('getItem', 'input-preset-reset', lambda: click_named(dialog, '恢复内置默认'))
                    file_box('getOpenFileName', 'file-import-preset', lambda: click_named(dialog, '从文件导入'))
                    file_box('getSaveFileName', 'file-save-preset', lambda: click_named(dialog, '导出所选风格'))
                modal('preset-library-long-name', window.library, library)
                window.style.setCurrentText(wet.document['style'])
            with stage('reference and preview'):
                def reference(dialog):
                    snapshot('reference-loaded', dialog, state='measured FLEURS and synthetic reference')
                    file_box('getOpenFileName', 'file-reference-audio',
                             lambda: click_named(dialog, '选择参考音频'))
                modal('reference-loaded', window.reference, reference)
                n = min(service.SR * 3, len(dry.original), len(wet.output))
                pair = dry.original[:n], wet.output[:n]
                levels = [service.engine.loudness(audio, service.SR) for audio in pair]
                for stage_name in (None, 'eq'):
                    with own(PreviewDialog(pair, levels, service.SR, None, .75, window, stage=stage_name)) as preview:
                        snapshot('preview-reference' if stage_name is None else 'preview-effect-stage', preview,
                                 state='audio prepared; playback not started')
            with stage('parameter tabs and canvases'):
                modal('parameters', window.parameters,
                      lambda d: capture_tabs(d, 'parameters', ('controls', 'chain', 'tail-positions', 'eq',
                                                              'pitch-compression', 'phrase-editor', 'automation')))
            with stage('analysis report tabs and canvases'):
                modal('report', window.report_view,
                      lambda d: capture_tabs(d, 'report', ('overview', 'segments', 'before-after', 'effects')))
            with stage('export format variants'):
                def exports(dialog):
                    for fmt in ('WAV', 'FLAC', 'MP3', 'AAC'):
                        dialog.format.setCurrentText(fmt)
                        snapshot('export-' + fmt.lower(), dialog)
                file_box('getSaveFileName', 'file-export-audio',
                         lambda: modal('export', window.export, exports, accepted=True))
                file_box('getSaveFileName', 'file-save-project', lambda: window.save(True))
            with stage('settings and updater'):
                def settings(dialog):
                    capture_tabs(dialog, 'settings', ('hardware', 'audio-folders', 'software-update', 'appearance'))
                    dialog.tabs.setCurrentIndex(1)
                    editor = dialog._paths['project_dir']
                    original = editor.text()
                    editor.setText(str(project_dir / LONG_TITLE / LONG_TITLE))
                    snapshot('settings-long-path', dialog, state='unsaved long directory')
                    editor.setText(original)
                    for directory_key, title in (('project_dir', '工程'), ('export_dir', '成品'),
                                                 ('cache_dir', '音频缓存')):
                        file_box('getExistingDirectory', 'file-select-' + directory_key,
                                 lambda e=dialog._paths[directory_key], t=title: dialog._browse(e, t))
                    dialog.tabs.setCurrentIndex(2)
                    dialog.url.setText('http://invalid.example/不会发起网络请求')
                    dialog._check()
                    dialog.accept()
                    snapshot('settings-validation-error', dialog, state='rejected non-HTTPS URL; no network')
                modal('settings', window.settings_view, settings)
                with own(UpdateDialog(window)) as updater:
                    snapshot('update-official-idle', updater, state='no update check requested')
                    # Supply presentation data only; never enter the job/network path.
                    updater.action.setEnabled(False)
                    updater.status.setText('正在校验官方版本与 Ed25519 签名…')
                    updater.progress.setRange(0, 0)
                    snapshot('update-official-checking', updater, state='local display fixture; no request sent')
                    updater.progress.setRange(0, 100)
                    updater.progress.setValue(0)
                    updater.action.setEnabled(True)
                    updater.failure('离线验证 · 官方发布清单无法读取。请稍后重试。此处未发起网络请求。')
                    snapshot('update-official-error', updater, state='offline sample passed to production failure handler')
                    updater.release = {'version': 'uiux-isolated-test'}
                    updater.package = str(project_dir / 'not-a-real-installer.exe')
                    message_box('question', 'update-install-confirmation', updater.act)
            with stage('models offline'):
                def model_dialog(dialog):
                    snapshot('model-center-uninstalled', dialog, state='isolated store, no model download')
                    message_box('information', 'model-details', dialog._details)
                    message_box('question', 'model-delete-confirmation', dialog._delete)
                    file_box('getExistingDirectory', 'file-model-storage-location', dialog._migrate)
                modal('model-center', window.models, model_dialog)

            active = 'real song and multitrack render'
            paths = {}
            for name, audio in [('Vocal', vocal), ('Instrumental', music), ('song-demo', vocal + music)]:
                path = project_dir / (name + '.wav')
                audioio.encode(path, audio, service.SR, 24)
                paths[name] = str(path)
            song_doc = storage.project(paths.pop('song-demo'), 'FLEURS 与合成伴奏')
            song_doc.update(mode='song', stems=paths)
            song_input = service.prepare(song_doc, cancel, progress)
            window.commit(song_input, reset=True)
            window.show_ready(song_input)
            with stage('song setup'):
                modal('song-stems-ready', window.song_mix)
            song = service.plan_song(song_input, cancel, progress)
            window.commit(song, reset=True)
            window.show_ready(song)
            snapshot('workstation-song-plan', window, state='real stem processing and mastering')
            report['audio_measurements']['song_lufs'] = round(float(song.measured['lufs']), 3)
            report['warnings'].extend(window.render_warnings(song))
            with stage('song review'):
                modal('song-review', window.song_mix)
                with own(SongDialog(list(service.engine.PRESETS), song.document['style'], has_stems=True,
                                    plan=song.document['song'], recommend=True, has_studio=True,
                                    parent=window)) as dialog:
                    snapshot('song-recommend-again', dialog)
                message_box('question', 'separation-confirmation', window.separate)
            with stage('studio empty'), own(StudioDialog({}, service.SR, window)) as studio:
                snapshot('studio-empty', studio, state='no clips')
            with stage('studio rendered, menu, rack and balance'):
                def studio_pages(studio):
                    wait_for(lambda: studio.cache is not None, 'Real Studio master render did not complete')
                    studio.wave.first = studio.wave.cursor = service.SR // 4
                    studio.wave.last = min(service.SR * 2, studio.session.frames)
                    studio._selection()
                    snapshot('studio-loaded', studio, state='two real tracks, bus rendered, region selected')
                    popup('menu-studio-timeline', lambda: studio._menu_at(studio.wave.mapToGlobal(QPoint(36, 36))))
                    input_box('getDouble', 'input-studio-region', studio._set_region, accept_count=1)
                    input_box('getDouble', 'input-studio-envelope', lambda: studio._edit('包络点…'))
                    input_box('getDouble', 'input-studio-move-selection', lambda: studio._edit('移动选区至…'))
                    missing = project_dir / '不存在的外部分轨.wav'
                    file_box('getOpenFileName', 'file-studio-relink',
                             lambda: studio._restore({'external_sources': {'Bass': str(missing)}}, {}))
                    message_box('warning', 'studio-error', lambda: studio._error('离线审计 · 无法定位演示片段。'))
                    snapshot('studio-error-status', studio, state='production warning status; no files changed')
                    file_box('getOpenFileName', 'file-studio-import', studio._import)
                    file_box('getSaveFileName', 'file-studio-export', studio._export)

                    def rack(dialog):
                        snapshot('studio-rack-vocal', dialog)
                        dialog.target.setCurrentIndex(dialog.target.findData('Master'))
                        snapshot('studio-rack-master', dialog)
                    modal('studio-rack', studio._rack, rack)

                    def balance(dialog):
                        snapshot('studio-balance', dialog, state='measured tracks and recommendations')
                        dialog.mode.setCurrentIndex(1)
                        snapshot('studio-match-loudness', dialog, state='no mix settings applied')

                    def balance_launch():
                        studio._balance()
                        wait_for(lambda: studio.future is None, 'Studio balance assessment did not finish')
                    modal('studio-balance', balance_launch, balance)
                modal('studio', window.studio, studio_pages)
        finally:
            active = 'cleanup'
            window.timer.stop()
            if window.worker:
                window.cancel()
            wait_for(lambda: window.worker is None, 'Workstation task did not cancel', 8)
            hardware = getattr(window, 'hardware_job', None)
            if hardware and hardware.isRunning() and not hardware.wait(5000):
                raise TimeoutError('Hardware probe could not be joined')
            window.close()
            for top in app.topLevelWidgets():
                if top.isVisible():
                    top.close()
            if not QThreadPool.globalInstance().waitForDone(5000):
                raise TimeoutError('Qt DSP worker did not finish during cleanup')
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            pump()

    # Guard against accidental production playback during future capture changes. This
    # is a hard failure, not a simulated audio implementation or success path.
    from vox.playback import Playback

    def forbidden_play(*_args, **_kwargs):
        message = 'Playback attempted by screenshot harness'
        report['errors'].append({'stage': active, 'message': message})
        raise AssertionError(message)

    def capture_exception(kind, exc, trace):
        report['errors'].append({'stage': active, 'message': str(exc),
                                 'traceback': ''.join(traceback.format_exception(kind, exc, trace))})
        traceback.print_exception(kind, exc, trace)

    hook = sys.excepthook
    sys.excepthook = capture_exception
    try:
        with patch.object(Playback, 'play', forbidden_play):
            work()
    except Exception as exc:  # noqa: BLE001 -- the harness must persist failure evidence
        record_error(active, exc)
    finally:
        sys.excepthook = hook
        qInstallMessageHandler(old_handler)
        report['status'] = 'finished'
        report['warnings'] = list(dict.fromkeys(report['warnings']))
        report['coverage'] = coverage(report['pages'])
        if (report['coverage']['application_surfaces'] != 15 or len(report['coverage']['menus']) != 2
                or report['coverage']['canvas_slot_count'] != 9):
            report['errors'].append({'stage': 'coverage',
                                     'message': 'Incomplete native surface coverage: expected 15 app surfaces, 2 menus and 9 canvas slots.'})
        report['summary'] = {
            'pages': len(report['pages']), 'error_count': len(report['errors']),
            'qt_warning_count': sum(msg['type'] == 'QtWarningMsg' for msg in report['qt_messages']),
            'pages_with_possible_clipping': [p['name'] for p in report['pages']
                                             if p['possible_clipping_control_indices']],
        }
        write_report(manifest, report)
        print(f"Captured {len(report['pages'])} PNGs; {len(report['errors'])} errors. {manifest}", flush=True)
    return int(bool(report['errors']))


if __name__ == '__main__':
    args = arguments()
    sys.exit(run_capture(args) if os.environ.get('_VOX_UIUX_CHILD') == '1' else supervise(args))
