"""Reproduce branch-only checks using disposable data and synthetic settings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(os.environ.get('SCMS_VERIFY_ROOT', str(Path.cwd()))).resolve()
PG_ROOT = Path(os.environ.get('SCMS_VERIFY_PG_ROOT', str(ROOT))).resolve()
OUT = Path(os.environ.get('SCMS_VERIFY_OUTPUT', str(ROOT/'build/evidence/pr93-integration-runtime'))).resolve()
PYTHON = os.environ.get('SCMS_VERIFY_PYTHON', sys.executable)
FOCUSED = [
    'complaints/test_anonymous.py', 'complaints/test_tracking.py',
    'routing/test_b12_privacy.py', 'routing/test_b15_http.py',
    'routing/test_allocation.py', 'routing/test_queue.py',
    'routing/test_resolver.py', 'routing/test_intake_routing.py',
    'routing/test_intake_entrypoint.py', 'routing/test_intake_allocation_integration.py',
    'routing/test_escalation.py', 'routing/test_escalation_outer_transaction.py',
    'routing/test_notification_handoff.py', 'workflow/test_reference_feedback.py',
    'workflow/test_notifications.py', 'workflow/test_autoclose.py',
    'workflow/test_email_retries.py', 'workflow/test_notification_smtp.py',
    'accounts/test_permissions.py', 'accounts/test_permissions_integration.py',
    'integration_checks/anonymous_escalation.py', 'integration_checks/anonymous_recovery.py',
    'integration_checks/lifecycle_f3.py', 'integration_checks/resolution_f3.py',
    'integration_checks/f3_f4_handoff.py', 'workflow/test_retired_anonymous_routes.py',
]

def main(stage):
    root = Path(os.environ.get('SCMS_VERIFY_Q05_ROOT', str(ROOT))) if stage.startswith('q05-') else (PG_ROOT if stage.endswith('-pg') else (Path(os.environ.get('SCMS_VERIFY_BROWSER_ROOT', str(ROOT))) if stage.startswith('browser') else ROOT))
    folder = OUT / stage
    folder.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env['PATH'] = str(Path(PYTHON).parent) + os.pathsep + env.get('PATH','')
    # Override all deployment-facing switches; fixtures alone may temporarily
    # enable them against synthetic local data. Never read a developer .env.
    env.update(DJANGO_SECRET_KEY='synthetic-branch-integration-test-only',
        DJANGO_SETTINGS_MODULE='scms.settings', DJANGO_DB_ENGINE='sqlite',
        DJANGO_DB_PATH=str(folder/'disposable.sqlite3'),
        PRIVATE_EVIDENCE_ROOT=str(folder/'private-evidence'), DJANGO_DEBUG='False',
        DJANGO_MAIL_BACKEND='console', DJANGO_SMTP_USE_TLS='True', DJANGO_SMTP_USE_SSL='False',
        COMPLAINT_INTAKE_ENABLED='False', ANONYMOUS_INTAKE_ENABLED='False',
        ANONYMOUS_FEEDBACK_ENABLED='False', ANONYMOUS_TRACKING_ENABLED='False',
        ANONYMOUS_PRIVACY_READY='False', ANONYMOUS_TRANSPORT_VERIFIED='False',
        ANONYMOUS_TRACKING_LIMITER_READY='False',
        SCMS_CI_DATABASE_ISOLATED='1', SCMS_CI_REQUIRE_F4='1', SCMS_CI_PYTHON=PYTHON)
    if stage.endswith('-pg'):
        env.update(DJANGO_SETTINGS_MODULE='scms.recovery_postgresql_settings',
            RECOVERY_POSTGRES_NAME='scms_integration', RECOVERY_POSTGRES_USER='scms_integration',
            RECOVERY_POSTGRES_PASSWORD='synthetic-integration-only',
            RECOVERY_POSTGRES_HOST='127.0.0.1', RECOVERY_POSTGRES_PORT=os.environ.get('SCMS_VERIFY_PG_PORT','55439'),
            PGHOST='127.0.0.1', PGPORT=os.environ.get('SCMS_VERIFY_PG_PORT','55439'), PGUSER='scms_integration',
            PGPASSWORD='synthetic-integration-only')
    if stage.startswith('full-'):
        env['PYTEST_ADDOPTS'] = '--junitxml='+str(folder/'junit.xml')
        command=['sh', 'scripts/ci_checks.sh', 'build/evidence/'+stage]
    elif stage.startswith('focused-'):
        command=[PYTHON, '-m', 'pytest', *FOCUSED, '--no-cov', '-q',
                 '--junitxml='+str(folder/'junit.xml')]
    elif stage.startswith('q05-'):
        env.update(DJANGO_SETTINGS_MODULE='q05_checks.settings',
            Q05_DB_NAME='scms_q05_integration', Q05_DB_USER='scms_integration',
            Q05_DB_PASSWORD='synthetic-integration-only', Q05_DB_HOST='127.0.0.1', Q05_DB_PORT=os.environ.get('SCMS_VERIFY_PG_PORT','55439'))
        command=[PYTHON, '-m', 'pytest', 'q05_checks/test_scheduler.py', 'q05_checks/test_smtp_recovery.py',
            'q05_checks/test_autoclose_recovery.py', '--no-cov', '-q', '--junitxml='+str(folder/'junit.xml')]
    elif stage.startswith('browser'):
        env['SCMS_BROWSER_EVIDENCE_DIR']=str(folder)
        command=[PYTHON, '-m', 'pytest', 'integration_checks/intake_browser.py',
            'integration_checks/reference_feedback_browser.py', '--no-cov', '-q',
            '--junitxml='+str(folder/'junit.xml')]
    else:
        raise SystemExit('Unknown stage')
    source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    dirty=subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip()
    record=dict(stage=stage, source_revision=source, working_tree_status=dirty,
        command=command, cwd=str(root), environment_overrides={k:v for k,v in env.items()
            if k not in os.environ or os.environ.get(k)!=v}, started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    (folder/'command.json').write_text(json.dumps(record,indent=2)+'\n')
    start=time.monotonic()
    with (folder/'console.txt').open('w') as log:
        result=subprocess.run(command,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
    record.update(exit_code=result.returncode,elapsed_seconds=round(time.monotonic()-start,3))
    (folder/'result.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:record[k] for k in ('stage','source_revision','exit_code','elapsed_seconds')}),flush=True)
    print((folder/'console.txt').read_text()[-5000:],flush=True)
    return result.returncode

if __name__=='__main__':
    raise SystemExit(main(sys.argv[1]))
