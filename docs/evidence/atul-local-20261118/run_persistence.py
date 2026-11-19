"""Verify the task-owned local image across app/DB restart and replacement.

Run only after HTTP measurement has stopped. Retains named volumes; no reset,
gate override, SMTP delivery or other project operation. Private retry key is
stored mode 0600 in the private Q04 state directory, never in evidence.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--repo',type=Path,required=True)
p.add_argument('--state',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--probe',type=Path,required=True)
args=p.parse_args()
sys.path.insert(0,str(args.repo))
from scripts.q04_env import compose
data=json.loads((args.state/'settings.json').read_text())
project=data['project'];app=project+'-app-1';db=project+'-db-1'
assert project.startswith('q04') and len(project)==15
args.output.mkdir(parents=True,exist_ok=False)
key=secrets.token_hex(32)
fd=os.open(args.state/'persistence-retry-key',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
with os.fdopen(fd,'w') as f:f.write(key)
report={'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=args.repo,text=True).strip(),
    'scope':'Local branch image/service acceptance and persistent-volume restart/replacement, not final Main deployment sign-off',
    'started_at_utc':datetime.now(timezone.utc).isoformat(),'project':project,'stages':{},'status':'RUNNING'}
def docker(*cmd):
    return subprocess.check_output(['docker',*cmd],text=True,timeout=90)
def identity():
    return {name:json.loads(docker('inspect',name,'--format','{"id":{{json .Id}},"image":{{json .Image}},"mounts":{{json .Mounts}}}')) for name in (app,db)}
def probe(stage,replay):
    r=subprocess.run(['docker','exec','-i',app,'python','manage.py','shell','-c',args.probe.read_text()],
        input=json.dumps({'key':key,'expect_replay':replay}),capture_output=True,text=True,timeout=60)
    if r.returncode:
        # No private stdin/keys in the diagnostic file.
        (args.output/(stage+'-error.txt')).write_text(r.stderr)
        raise RuntimeError('Persistence probe failed: '+stage)
    item=json.loads(next(x[len('Q05_PERSISTENCE_JSON:'):] for x in r.stdout.splitlines() if x.startswith('Q05_PERSISTENCE_JSON:')))
    report['stages'][stage]=item
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return item
def wait_healthy():
    until=time.monotonic()+90
    while time.monotonic()<until:
        if all(docker('inspect',n,'--format','{{.State.Health.Status}}').strip()=='healthy' for n in (app,db)):return
        time.sleep(1)
    raise RuntimeError('Task-owned containers did not become healthy')
try:
    report['before']=identity()
    first=probe('accepted_before_restart',False)
    docker('restart',db);docker('restart',app);wait_healthy()
    second=probe('after_restart',True)
    with (args.output/'replacement-console.txt').open('w') as log:
        compose(data,'up','-d','--force-recreate','--no-build','--wait','--wait-timeout','90',stdout=log,stderr=subprocess.STDOUT)
    third=probe('after_container_replacement',True)
    report['after']=identity()
    for field in ('graph_sha256','evidence_sha256','counts','file_mode','release_gates','evidence_max_bytes'):
        assert first[field]==second[field]==third[field],field
    for name in (app,db):
        assert report['before'][name]['id']!=report['after'][name]['id']
        assert report['before'][name]['image']==report['after'][name]['image']
        assert report['before'][name]['mounts']==report['after'][name]['mounts']
    assert first['file_mode']=='0o600'
    report['status']='LOCAL_PERSISTENCE_PASS'
except BaseException as exc:
    report['status']='FAIL';report['failure_category']=type(exc).__name__
    if isinstance(exc,RuntimeError):report['failure']=str(exc)
finally:
    report['finished_at_utc']=datetime.now(timezone.utc).isoformat()
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('status','source_revision','started_at_utc','finished_at_utc')}))
raise SystemExit(0 if report['status']=='LOCAL_PERSISTENCE_PASS' else 2)
