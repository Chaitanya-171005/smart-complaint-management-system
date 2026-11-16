"""Execute CI shell bodies to guard failure propagation and disposable storage.

The tiny Python stand-in tests shell control flow, not browser/Redis acceptance.
"""
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parent


def step(filename, name):
    text = (ROOT / '.github/workflows' / filename).read_text()
    match = re.search(r'^      - name: ' + re.escape(name) + r'\n(.*?)(?=^      - |\Z)',
                      text, re.MULTILINE | re.DOTALL)
    assert match, 'Required workflow step is missing.'
    body = match[1]
    assert re.search(r'^        shell: bash$', body, re.MULTILINE)
    script = body.split('        run: |\n', 1)[1]
    return '\n'.join(line[10:] for line in script.splitlines() if line.strip()) + '\n'


@pytest.mark.parametrize('filename,name,log', [
    ('intake-browser.yml', 'Normal submissions and accessible inline errors at 320 pixels',
     'build/evidence/intake-browser/pytest.txt'),
    ('b13-redis.yml', 'Execute real Redis and real TLS proxy checks (no skips)',
     'build/evidence/b13-review/real-redis-proxy.txt'),
])
@pytest.mark.parametrize('exit_code', [0, 7])
def test_pytest_pipeline_keeps_failure_exit_status(tmp_path, filename, name, log, exit_code):
    executable = tmp_path / 'python'
    executable.write_text('#!/bin/sh\nprintf "synthetic shell-control check\\n"\nexit "$WORKFLOW_TEST_EXIT"\n')
    executable.chmod(0o700)
    script = tmp_path / 'step.sh'
    script.write_text(step(filename, name))
    # Match even bash -e without GitHub's implicit extra flags: the script
    # itself must prevent tee from hiding a failing pytest process.
    completed = subprocess.run(['bash', '-e', str(script)], cwd=tmp_path, capture_output=True,
        text=True, env=dict(os.environ, PATH=str(tmp_path)+os.pathsep+os.environ['PATH'],
                           WORKFLOW_TEST_EXIT=str(exit_code)), timeout=10)
    assert completed.returncode == exit_code
    assert (tmp_path / log).read_text() == 'synthetic shell-control check\n'


def test_ci_storage_is_unique_and_does_not_reuse_existing_database(tmp_path):
    original = tmp_path / 'developer.sqlite3'
    original.write_bytes(b'original unrelated database')
    temporary = tmp_path / 'runner temp with spaces'
    temporary.mkdir()
    script = tmp_path / 'prepare.sh'
    script.write_text(step('b13-redis.yml', 'Prepare disposable CI database and evidence storage'))
    databases = []
    for attempt in range(2):
        exported = tmp_path / f'github-env-{attempt}'
        result = subprocess.run(['bash', '-e', str(script)], cwd=tmp_path, capture_output=True,
            text=True, env=dict(os.environ, RUNNER_TEMP=str(temporary), GITHUB_ENV=str(exported),
                               DJANGO_DB_PATH=str(original)), timeout=10)
        assert result.returncode == 0, result.stderr
        values = dict(line.split('=', 1) for line in exported.read_text().splitlines())
        database = Path(values['DJANGO_DB_PATH'])
        assert database.parent.parent == temporary and not database.exists()
        assert Path(values['PRIVATE_EVIDENCE_ROOT']).is_dir()
        assert values['SCMS_CI_DATABASE_ISOLATED'] == '1'
        databases.append(database)
    assert databases[0] != databases[1]
    assert original.read_bytes() == b'original unrelated database'
