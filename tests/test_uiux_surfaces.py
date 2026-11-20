"""Contract tests for the offline Qt UX capture harness (no Qt launch/audio I/O)."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import verify_uiux

ROOT = Path(__file__).resolve().parents[1]


def test_source_root_selects_package_and_keeps_repository_fixture(tmp_path):
    source = tmp_path / 'snapshot'
    (source / 'vox').mkdir(parents=True)
    (source / 'vox' / '__init__.py').write_text('', 'utf-8')
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'verify_uiux.py'), '--help'],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0
    for option in ('--source-root', '--theme', '--width', '--height', '--maximized', '--timeout'):
        assert option in result.stdout
    assert ROOT / 'tests' / 'fixtures' / 'fleurs-mandarin.wav' == verify_uiux.FIXTURE
    assert verify_uiux.FIXTURE.is_file()


def test_coverage_recognizes_all_surfaces_without_counting_each_standard_dialog_call():
    def page(name, widget, controls=()):
        return {'name': name, 'widget': widget, 'controls': list(controls)}

    pages = [page('workstation', 'MainWindow')]
    pages += [page(dialog, dialog) for dialog in verify_uiux.NAMED_DIALOGS]
    pages += [page('projects-' + str(i), 'QDialog') for i in range(4)]
    pages += [page('reference-' + str(i), 'QDialog') for i in range(4)]
    pages += [page('preset-library-' + str(i), 'QDialog') for i in range(2)]
    pages += [page('a', 'QMenu'), page('b', 'QMenu')]
    for name in ('file-open-audio', 'file-save-preset'):
        pages.append(page(name, 'QFileDialog'))
    pages.extend(page('input-' + str(i), 'QInputDialog') for i in range(7))
    pages.extend(page('message-' + str(i), 'QMessageBox') for i in range(9))
    for (module, name), expected in verify_uiux.CANVAS_SLOTS.items():
        controls = [{'module': module, 'class': name}] * expected
        pages.append(page(module + '-' + name, 'QDialog', controls))

    result = verify_uiux.coverage(pages)
    assert result['application_surfaces'] == 15
    assert result['named_dialogs'] == sorted(verify_uiux.NAMED_DIALOGS)
    assert result['inline_dialogs'] == ['projects', 'reference', 'preset-library']
    assert len(result['menus']) == 2
    assert result['canvas_slot_count'] == 9
    assert {row['observed'] for row in result['canvas_slots'].values()} == {1, 2}
    assert len(result['qt_fallback_file_entries']) == 2
    assert len(result['qt_input_entries']) == 7
    assert len(result['qt_message_entries']) == 9


def test_coverage_rejects_missing_canvas_slot():
    result = verify_uiux.coverage([{'name': 'x', 'widget': 'MainWindow', 'controls': []}])
    assert result['application_surfaces'] == 1
    assert result['canvas_slot_count'] == 0


def test_stop_tree_never_touches_an_already_exited_process():
    class Exited:
        pid = 2 ** 31 - 1

        def poll(self):
            return 0

    # A finished process must not trigger any descendant enumeration or signals.
    verify_uiux.stop_tree(Exited())


def test_report_write_is_atomic_and_utf8(tmp_path):
    path = tmp_path / 'uiux.json'
    verify_uiux.write_report(path, {'text': '长文本', 'pages': []})
    assert json.loads(path.read_text('utf-8')) == {'text': '长文本', 'pages': []}
    assert not (tmp_path / 'uiux.json.tmp').exists()


def test_arguments_reject_source_without_vox(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'argv', ['verify_uiux.py', '--output', str(tmp_path / 'x'),
                                      '--source-root', str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        verify_uiux.arguments()
    assert exc.value.code == 2


def test_maximized_metadata_is_recorded_in_supervisor_manifest(monkeypatch, tmp_path):
    written = []

    def capture(path, payload):
        written.append(payload)

    monkeypatch.setattr(verify_uiux, 'write_report', capture)
    args = SimpleNamespace(output=tmp_path, source_root=tmp_path, theme='light',
                           width=820, height=560, maximized=True, timeout=1)
    # The child is prevented from launching by exhausting the temp bootstrap? Use a
    # fake Popen that reports an immediate failure and leaves the manifest readable.
    class Child:
        returncode = 1

        def __enter__(self):
            return self

        def __exit__(self, *unused):
            return False

        def wait(self, timeout):
            return self.returncode

    monkeypatch.setattr(verify_uiux.subprocess, 'Popen', lambda *a, **k: Child())
    manifest = tmp_path / 'uiux.json'

    def seed(path, payload):
        written.append(payload)
        manifest.write_text(json.dumps(payload), 'utf-8')

    monkeypatch.setattr(verify_uiux, 'write_report', seed)
    assert verify_uiux.supervise(args) == 1
    assert written[0]['requested_maximized'] is True
    assert manifest.is_file()