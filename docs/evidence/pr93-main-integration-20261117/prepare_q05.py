"""Materialize archived component tests beside a disposable integration clone.

Only the SMTP closed-port fixture is adapted for macOS. Historical payloads and
application sources remain untouched. Run sequentially after other PG tests.
"""
import difflib
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
target = root / 'q05_checks'
target.mkdir(exist_ok=False)
archives = root / 'docs/evidence'
sources = {
    '__init__.py': 'q05-smtp-postgresql/sources/q05_checks/__init__.py.txt',
    'settings.py': 'q05-smtp-postgresql/sources/q05_checks/settings.py.txt',
    'test_scheduler.py': 'q05-scheduler-postgresql/sources/q05_checks/test_scheduler.py.txt',
    'test_smtp_recovery.py': 'q05-smtp-postgresql/sources/q05_checks/test_smtp_recovery.py.txt',
    'test_autoclose_recovery.py': 'q05-autoclose-postgresql/sources/q05_checks/test_autoclose_recovery.py.txt',
}
for name, source in sources.items():
    (target / name).write_bytes((archives / source).read_bytes())
p = target / 'test_smtp_recovery.py'
original = p.read_text()
old = """    with socket.socket() as unused:
        unused.bind(('127.0.0.1', 0))  # Bound but not listening: actual ECONNREFUSED.
        settings.MAILERS = {'default': {'BACKEND': 'django.core.mail.backends.smtp.EmailBackend',
            'OPTIONS': {'host': '127.0.0.1', 'port': unused.getsockname()[1], 'timeout': 2}}}
        assert deliver_email(job.pk) == 'RETRY_WAIT'
"""
new = """    with socket.socket() as unused:
        unused.bind(('127.0.0.1', 0))
        port = unused.getsockname()[1]
    # Close the reservation before connecting. A bound but non-listening socket
    # can time out on macOS; that correctly takes the ambiguous-delivery path.
    settings.MAILERS = {'default': {'BACKEND': 'django.core.mail.backends.smtp.EmailBackend',
        'OPTIONS': {'host': '127.0.0.1', 'port': port, 'timeout': 2}}}
    assert deliver_email(job.pk) == 'RETRY_WAIT'
"""
assert original.count(old) == 1, 'Archived fixture changed; inspect before adapting.'
p.write_text(original.replace(old, new))
print(json.dumps({name: hashlib.sha256((target/name).read_bytes()).hexdigest()
                  for name in sources}, indent=2))
