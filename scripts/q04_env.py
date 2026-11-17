#!/usr/bin/env python3
"""Operate a disposable Q04 stack; no load test runs without explicit consent."""
import argparse
import hashlib
import json
import re
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[1]
STATE = Path.home() / '.scms-q04' / hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
COMPOSE = ROOT / 'q04' / 'compose.yml'

def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(text)
    if os.name != 'nt':
        os.chmod(path, 0o600)

def invoke(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)

def get_settings(create=False, port=None, count=None, random_seed=None):
    path=STATE/'settings.json'
    if not path.exists():
        if not create: raise ValueError('Environment not initialized; run up first.')
        port = 55004 if port is None else port
        count = 650 if count is None else count
        random_seed = 0 if random_seed is None else random_seed
        if not 1024 <= port <= 65535 or not 600 <= count <= 100000: raise ValueError('Invalid port or complaint count.')
        data={'project':'q04'+secrets.token_hex(6),'port':port,'complaints':count,'seed':random_seed,'password':secrets.token_urlsafe(24),'db_password':secrets.token_hex(24),'secret_key':secrets.token_hex(32)}
        private_write(path,json.dumps(data))
    data=json.loads(path.read_text())
    if not re.fullmatch(r'q04[0-9a-f]{12}',data.get('project','')): raise ValueError('Invalid Q04 project identity')
    data.setdefault('seed',0)  # Legacy prototype did not record a seed.
    for key,value in (('port',port),('complaints',count),('seed',random_seed)):
        if value is not None and data[key]!=value: raise ValueError(f'{key} differs: existing={data[key]}, requested={value}; use --environment NAME with a different port for a separate project')
    return data

def compose(data, *args, **kwargs):
    env=os.environ.copy()
    env.update(Q04_PORT=str(data['port']),Q04_DB_PASSWORD=data['db_password'],Q04_SECRET_KEY=data['secret_key'],Q04_IMAGE=data['project']+':local')
    return invoke(['docker','compose','-p',data['project'],'-f',str(COMPOSE),*args],cwd=ROOT,env=env,**kwargs)

def seed(data):
    script=(ROOT/'scripts'/'q04_seed.py').read_text()
    proc=compose(data,'exec','-T','app','python','manage.py','shell','-c',script,input=json.dumps({'password':data['password'],'complaints':data['complaints'],'seed':data['seed']}),text=True,capture_output=True)
    line=next((x for x in proc.stdout.splitlines() if x.startswith('Q04_JSON:')),None)
    if not line: raise ValueError('Seed returned no result')
    result=json.loads(line[9:])
    private_write(STATE/'actors.json',json.dumps(result['actors']))
    print(f"Seeded: 50 complainants, 50 heads, 2 staff, {result['count']} complaints; {result['reserved_unassigned']} targets available.")
    return result

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def http(port,path,cookie=None):
    req=Request(f'http://127.0.0.1:{port}'+path,headers={'Cookie':'sessionid='+cookie} if cookie else {})
    try: response=build_opener(NoRedirect()).open(req,timeout=10)
    except HTTPError as e: response=e
    with response: return response.status,response.read().decode('utf-8','replace')

def release_gates(data):
    code="import json; from django.conf import settings; print(json.dumps({'intake': bool(settings.COMPLAINT_INTAKE_ENABLED and settings.COMPLAINT_EMERGENCY_NOTICE), 'anonymous': bool(settings.ANONYMOUS_INTAKE_ENABLED and settings.ANONYMOUS_PRIVACY_READY and settings.ANONYMOUS_TRANSPORT_VERIFIED)}))"
    result=compose(data,'exec','-T','app','python','manage.py','shell','-c',code,text=True,capture_output=True)
    return json.loads(result.stdout.splitlines()[-1])

def sessions_valid(data):
    path=STATE/'actors.json'
    if not path.exists(): return False
    try:
        actors=json.loads(path.read_text())
        for role, expected in (('HEAD',200),('COMPLAINANT',403)):
            entries=actors[role]
            if len(entries)!=50 or len({x['session_cookie'] for x in entries})!=50: return False
            for entry in entries:
                status,body=http(data['port'],'/routing/queue/',entry['session_cookie'])
                if status!=expected or (role=='HEAD' and 'Q04 synthetic complaint' not in body): return False
        probe="from complaints.models import Complaint; print(Complaint.objects.filter(title__startswith='Q04 synthetic complaint ').count())"
        result=compose(data,'exec','-T','app','python','manage.py','shell','-c',probe,text=True,capture_output=True)
        return result.stdout.splitlines()[-1].strip() == str(data['complaints'])
    except (ValueError, KeyError, OSError, URLError, subprocess.CalledProcessError):
        return False

def check(data):
    gates=release_gates(data)
    actors=json.loads((STATE/'actors.json').read_text())
    head=actors['HEAD'][0]['session_cookie']; complainant=actors['COMPLAINANT'][0]['session_cookie']
    checks=[('queue', '/routing/queue/',head),('queue page 2','/routing/queue/?page=2',head),('authenticated intake','/complaints/new/',complainant),('anonymous intake','/anonymous/new/',None),('tracking','/anonymous/track/',None),('reporting','/reports/',None),('acknowledgement (no receipt)','/complaints/SCMS-2099-000001/submitted/',complainant)]
    queue_body=''
    for name,path,cookie in checks:
        status,body=http(data['port'],path,cookie)
        if name=='queue' and status==200: queue_body=body
        gated=(name=='authenticated intake' and not gates['intake']) or (name=='anonymous intake' and (not gates['anonymous'] or not gates['intake']))
        label='READY' if status==200 else 'RELEASE_GATED' if status==503 and gated else 'ROUTE_UNAVAILABLE' if status==404 and name in ('tracking','reporting') else 'NOT_VERIFIED' if status==404 and name.startswith('acknowledgement') else 'FAILED'
        extra=f", rows={body.count('<article>')}" if name.startswith('queue') and status==200 else ''
        print(f'{name}: {label} (HTTP {status}{extra})')
    assignment='NOT_VERIFIED' if '/assign/' in queue_body else 'FAILED'
    print(f'assignment form: {assignment}; evidence upload/download: NOT_VERIFIED')
    try:
        compose(data,'exec','-T','app','python','manage.py','run_escalation','--help',text=True,capture_output=True)
        print('escalation command: NOT_VERIFIED (command exists; not executed)')
    except subprocess.CalledProcessError:
        print('escalation command: FAILED')

@contextmanager
def environment_lock():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    stream = open(STATE/'operation.lock', 'a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            stream.seek(0); stream.write(b'0'); stream.flush(); stream.seek(0)
            try: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError: raise ValueError('Another Q04 operation is running') from None
        else:
            import fcntl
            try: fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('Another Q04 operation is running') from None
        yield
    finally:
        stream.close()

def verify_volume_ownership(data):
    project=data['project']
    if not re.fullmatch(r'q04[0-9a-f]{12}',project): raise ValueError('Invalid Q04 project identity')
    expected={f'{project}_q04_database',f'{project}_q04_evidence'}
    listing=invoke(['docker','volume','ls','--filter',f'label=com.docker.compose.project={project}','--format','{{.Name}}'],capture_output=True,text=True)
    if set(listing.stdout.splitlines()) != expected: raise ValueError('Unexpected or missing project volumes; refusing reset')
    for kind in ('q04_database','q04_evidence'):
        proc=invoke(['docker','volume','inspect',f'{project}_{kind}'],capture_output=True,text=True)
        labels=(json.loads(proc.stdout)[0].get('Labels') or {})
        if labels.get('com.docker.compose.project')!=project or labels.get('com.docker.compose.volume')!=kind:
            raise ValueError('Volume ownership mismatch; refusing reset')

def recover_preflight():
    marker=STATE/'action-targets-consumed'
    if not marker.exists(): raise ValueError('No run reservation to recover')
    raw=marker.read_text()
    try: record=json.loads(raw)
    except (ValueError, TypeError): record={'phase':raw, 'state':raw}
    if record.get('phase') != 'preflight' or record.get('state') not in ('preflight','failed','interrupted'):
        raise ValueError('Recovery only clears an interrupted preflight; running or unknown state needs investigation')
    marker.unlink()

def write_run_state(marker, record, state, phase):
    record.update(state=state,phase=phase,updated_at=datetime.now(timezone.utc).isoformat())
    tmp=marker.with_name(marker.name+'.tmp')
    private_write(tmp,json.dumps(record))
    os.replace(tmp,marker)


def main():
    global STATE
    p=argparse.ArgumentParser(); p.add_argument('command',choices=('up','status','config','seed','check','down','reset','recover','run')); p.add_argument('--port',type=int);p.add_argument('--complaints',type=int);p.add_argument('--random-seed',type=int);p.add_argument('--confirm',action='store_true');p.add_argument('--project');p.add_argument('--environment',default='default')
    args=p.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,31}',args.environment): raise ValueError('Invalid environment name')
    if args.environment != 'default': STATE=STATE/'environments'/args.environment
    with environment_lock():
        execute(args)

def execute(args):
    if args.command != 'config' and not shutil.which('docker'): raise ValueError('Docker CLI is not installed')
    data=get_settings(args.command=='up',args.port,args.complaints,args.random_seed)
    if (STATE/'action-targets-consumed').exists() and args.command in ('up','seed','down','reset','run'):
        raise ValueError('Benchmark reservation exists; investigate before changing this environment')
    if args.command=='config':
        stored=json.loads((STATE/'settings.json').read_text())
        print(json.dumps({'project':data['project'],'port':data['port'],'complaints':data['complaints'],'seed':data['seed'],'seed_recorded': 'seed' in stored,'environment':args.environment},indent=2))
    elif args.command=='up':
        compose(data,'up','-d','--build','--wait', '--wait-timeout','180')
        compose(data,'exec','-T','app','python','manage.py','check')
        if sessions_valid(data): print('Existing synthetic sessions are valid; reusing them.')
        else: seed(data)
        check(data)
        print(f"Local test URL: http://127.0.0.1:{data['port']}; private data: {STATE}")
    elif args.command=='seed': seed(data)
    elif args.command=='status': compose(data,'ps')
    elif args.command=='check': check(data)
    elif args.command=='down': compose(data,'down')
    elif args.command=='reset':
        if not args.confirm: raise ValueError('Reset requires --confirm and deletes only this Q04 project volumes.')
        if args.project != data['project']: raise ValueError('Reset requires the exact --project shown by config')
        verify_volume_ownership(data)
        compose(data,'down','--volumes','--remove-orphans')
        (STATE/'actors.json').unlink(missing_ok=True)
        print('Removed verified project volumes; rerun up to initialize.')
    elif args.command=='recover':
        if not args.confirm: raise ValueError('Recovery requires --confirm')
        recover_preflight()
        print('Cleared an interrupted preflight reservation; no benchmark was launched.')
    elif args.command=='run':
        if not args.confirm: raise ValueError('Benchmark requires --confirm; it sends 50 concurrent users.')
        marker=STATE/'action-targets-consumed'
        try: fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError: raise ValueError('Targets are reserved by a previous or concurrent run; inspect before recovery')
        os.close(fd)
        record={'run_id':uuid.uuid4().hex}
        write_run_state(marker,record,'preflight','preflight')
        try:
            run_preflight_and_execute(data, marker, record)
        except BaseException as exc:
            phase=record['phase']
            write_run_state(marker,record,'interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',phase)
            raise

def run_preflight_and_execute(data, marker, record):
        actors=json.loads((STATE/'actors.json').read_text())
        heads=actors.get('HEAD',[])
        if len(heads)!=50 or len({x['session_cookie'] for x in heads})!=50: raise ValueError('50 distinct head sessions required')
        complainants=actors.get('COMPLAINANT',[])
        if len(complainants)!=50 or len({x['session_cookie'] for x in complainants})!=50: raise ValueError('50 distinct complainant sessions required')
        for actor in complainants:
            status,_=http(data['port'],'/routing/queue/',actor['session_cookie'])
            if status!=403: raise ValueError('A complainant session is expired or can access the head queue')
        targets=[x for h in heads for x in h['operations']['action']]
        expected_paths={f'/complaints/SCMS-2099-{i:06d}/assign/' for i in range(1,551)}
        if len(targets)!=550 or {x['path'] for x in targets}!=expected_paths or any(x.get('payload',{}).get('expected_assignee') != '' for x in targets): raise ValueError('550 distinct unassigned Q04 targets required')
        for h in heads:
            status,body=http(data['port'],'/routing/queue/',h['session_cookie'])
            if status!=200 or 'Q04 synthetic complaint' not in body: raise ValueError('A head session is invalid or expired')
        probe="from complaints.models import Complaint; print(Complaint.objects.filter(complaint_id__in=[f'SCMS-2099-{i:06d}' for i in range(1,551)], status='ASSIGNED', assignee__isnull=True, department__name='Q04 Synthetic Services').count())"
        result=compose(data,'exec','-T','app','python','manage.py','shell','-c',probe,text=True,capture_output=True)
        if not result.stdout.splitlines()[-1].strip() == '550': raise ValueError('Prepared targets are consumed or unavailable')
        config=json.loads((ROOT/'docs'/'performance'/'q04.example.json').read_text())
        sha=invoke(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip()
        config['environment']={'source_revision':sha,'database_engine':'postgresql','dataset_description':f"{data['complaints']} synthetic complaints; source checkout may be dirty",'network_conditions':'loopback, no shaping'}
        for case in config['cases']:
            if case['name']=='queue': case.update(enabled=True,expect_pattern='Q04 synthetic complaint',record_pattern='<article>',min_records=1,max_records=25)
            if case['name']=='action': case.update(enabled=True,path='/complaints/SCMS-2099-000001/assign/',expect_pattern='^/routing/queue/')
        if (STATE/'report.json').exists(): raise ValueError('Previous report exists; refusing to overwrite it')
        private_write(STATE/'benchmark.json',json.dumps(config))
        env=os.environ.copy(); env['SCMS_Q04_BASE_URL']=f"http://127.0.0.1:{data['port']}"
        write_run_state(marker,record,'running','execution')
        invoke([sys.executable,str(ROOT/'scripts'/'q04_load.py'),'--config',str(STATE/'benchmark.json'),'--actors',str(STATE/'actors.json'),'--output',str(STATE/'report.json')],cwd=ROOT,env=env)
        write_run_state(marker,record,'completed','execution')
if __name__=='__main__':
    try: main()
    except (ValueError, OSError, subprocess.CalledProcessError, URLError) as exc:
        print(f'Q04 error: {type(exc).__name__}: {exc}',file=sys.stderr);sys.exit(1)
