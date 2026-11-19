"""Run the real teardown plugin in child processes so false-green exits are visible."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest


@pytest.mark.parametrize(
    ('source', 'extra_args', 'expected_status', 'failures', 'errors'),
    [
        ('def test_ok():\n    assert True\n', [], 0, 0, 0),
        ('def test_bad():\n    assert False\n', [], 1, 1, 0),
        ('raise RuntimeError("collection failed")\n', [], 2, 0, 1),
        ('# No tests collected.\n', [], 5, 0, 0),
        ('def test_ok():\n    pass\n', ['--unrecognized-audit-option'], 4, None, None),
    ],
)
def test_teardown_preserves_pytest_process_status(
    tmp_path, source, extra_args, expected_status, failures, errors
):
    shutil.copyfile(Path(__file__).with_name('conftest.py'), tmp_path / 'conftest.py')
    (tmp_path / 'test_child.py').write_text(source, encoding='utf-8')
    report = tmp_path / 'results.xml'
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    env.pop('PYTEST_ADDOPTS', None)
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '--junitxml=' + str(report), *extra_args],
        cwd=tmp_path, env=env, capture_output=True, timeout=60,
    )
    assert result.returncode == expected_status, (result.stdout, result.stderr)
    if failures is not None:
        suite = next(ET.parse(report).getroot().iter('testsuite'))
        assert int(suite.attrib['failures']) == failures
        assert int(suite.attrib['errors']) == errors
