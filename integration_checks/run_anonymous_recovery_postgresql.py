"""Run authenticated and anonymous recovery checks on PostgreSQL; refuse fallback and skipped tests."""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scms.recovery_postgresql_settings')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import django
from django.db import connection

django.setup()
if connection.vendor != 'postgresql':
    raise SystemExit('PostgreSQL is required; SQLite cannot establish these checks.')
connection.ensure_connection()
output = Path(sys.argv[1] if len(sys.argv) > 1 else 'build/evidence/b11-recovery-postgresql')
output.mkdir(parents=True, exist_ok=True)
report = {
    'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    'working_tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()),
    'database_vendor': connection.vendor, 'postgresql_version': connection.pg_version,
    'python_version': platform.python_version(), 'django_version': django.get_version(),
    'scope': 'Authenticated and anonymous recovery component checks; final F3/F4 privacy and deployment acceptance remain pending',
}
print(json.dumps({key: value for key, value in report.items() if key != 'scope'}), flush=True)
connection.close()
completed = subprocess.run([sys.executable, '-m', 'pytest', '-o', 'addopts=',
    'complaints/test_evidence_recovery.py', 'integration_checks/anonymous_recovery.py', '-ra', '--color=no',
    '--junitxml=' + str(output / 'junit.xml')], text=True, capture_output=True)
(output / 'pytest.txt').write_text(completed.stdout + completed.stderr)
print(completed.stdout, end='', flush=True)
print(completed.stderr, end='', file=sys.stderr, flush=True)
report['pytest_exit_code'] = completed.returncode
cases = list(ET.parse(output / 'junit.xml').iter('testcase')) if (output / 'junit.xml').is_file() else []
report['executed_cases'] = len(cases)
report['skipped'] = sum(case.find('skipped') is not None for case in cases)
report['failed_or_errored'] = sum(case.find('failure') is not None or case.find('error') is not None for case in cases)
passed = completed.returncode == 0 and len(cases) == 34 and report['skipped'] == report['failed_or_errored'] == 0
report['status'] = 'PASS_COMPONENT_CHECKS' if passed else 'FAIL'
(output / 'run.json').write_text(json.dumps(report, indent=2) + '\n')
raise SystemExit(0 if passed else 2)
