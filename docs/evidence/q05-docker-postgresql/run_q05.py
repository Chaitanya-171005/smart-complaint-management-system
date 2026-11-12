"""Run an isolated E03 PostgreSQL/container persistence check on the user's Docker."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
from uuid import uuid4
import zipfile

REPO='Chaitanya-171005/smart-complaint-management-system'
BRANCH='feature/E03-docker-jenkins'
REVISION='526a0d31ea4a50f666b641839177a87e79c81f6b'


def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()


def write_json(path,value):
    with open(path,'x',opener=lambda file,flags:os.open(file,flags,0o600)) as stream:
        json.dump(value,stream,indent=2);stream.write('\n')


def finish(bundle):
    root=Path(subprocess.check_output(['git','rev-parse','--show-toplevel'],text=True).strip())
    assert git(root,'remote','get-url','origin') in {
        f'https://github.com/{REPO}.git',f'https://github.com/{REPO}',f'git@github.com:{REPO}.git'}, 'Unexpected repository.'
    assert shutil.which('docker'), 'Docker CLI is missing. Install/open Docker Desktop, then rerun.'
    assert subprocess.run(['docker','info'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0, 'Start Docker Desktop and wait until its engine is running, then rerun.'
    assert subprocess.run(['docker','compose','version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0, 'Docker Compose v2 is required.'
    subprocess.run(['git','-C',str(root),'fetch','origin',f'refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}'],check=True)
    assert git(root,'rev-parse','origin/'+BRANCH)==REVISION, 'E03 branch changed; stop and share the output before testing another revision.'
    run_id=uuid4().hex[:12]
    directory=Path.home()/'scms-q05-runs'/run_id
    directory.mkdir(parents=True,mode=0o700)
    source=directory/'source'
    subprocess.run(['git','-C',str(root),'worktree','add','--detach',str(source),REVISION],check=True)
    assert not git(source,'status','--porcelain')
    project='scmsq05'+run_id
    values={'DJANGO_SECRET_KEY':secrets.token_urlsafe(48),'DJANGO_DB_NAME':'q05_test',
        'DJANGO_DB_USER':'q05_test','DJANGO_DB_PASSWORD':secrets.token_hex(32),
        'DJANGO_ALLOWED_HOSTS':'localhost,127.0.0.1','APP_PORT':'127.0.0.1:0',
        'COMPLAINT_INTAKE_ENABLED':'False','COMPLAINT_EMERGENCY_NOTICE':'SYNTHETIC TEST ONLY'}
    env_file=directory/'private.env'
    with open(env_file,'x',opener=lambda file,flags:os.open(file,flags,0o600)) as stream:
        for name,value in values.items(): stream.write(name+'='+value+'\n')
    environment=dict(os.environ,**values)
    compose=['docker','compose','--project-name',project,'--env-file',str(env_file),
             '--file',str(source/'docker-compose.yml')]
    report={'run_id':run_id,'started_at_utc':datetime.now(timezone.utc).isoformat(),'status':'RUNNING',
        'tested_source':{'repository':REPO,'branch':BRANCH,'revision':REVISION,'working_tree_dirty':False},
        'scope':'Pinned E03 snapshot: PostgreSQL intake rollback/retry and named-volume container persistence',
        'phases':[],'remaining_q05':['final_merged_application','PR76_crash_reconciliation_on_postgresql',
            'scheduler_overlap_and_interruption','auto_close_vs_feedback','real_notification_outbox_failures']}
    with zipfile.ZipFile(bundle) as archive:
        probe=archive.read('probe.py').decode()
        report['probe_sha256']=hashlib.sha256(probe.encode()).hexdigest()
        report['driver_sha256']=hashlib.sha256(archive.read('run_q05.py')).hexdigest()

    def dc(*args,capture=False,input=None):
        result=subprocess.run([*compose,*args],env=environment,text=True,input=input,
                              stdout=subprocess.PIPE if capture else None,
                              stderr=subprocess.PIPE if capture else None)
        if result.returncode:
            raise RuntimeError('Docker check failed during '+args[0]+'. Test resources were retained; no pass is recorded.')
        return result.stdout.strip() if capture else ''

    def inspect(identifier,template):
        return subprocess.check_output(['docker','inspect','--format',template,identifier],text=True).strip()

    def healthy():
        deadline=time.monotonic()+300
        for service in ('db','app'):
            while True:
                identifier=dc('ps','-q',service,capture=True)
                if identifier:
                    status=inspect(identifier,'{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}')
                    if status=='healthy': break
                    if status in ('unhealthy','exited','dead'): raise RuntimeError(service+' did not become healthy.')
                if time.monotonic()>=deadline: raise RuntimeError('Timed out waiting for isolated test containers.')
                time.sleep(2)

    def containers():
        return {name:dc('ps','-q',name,capture=True) for name in ('app','db')}

    def volumes(ids):
        targets={'app':'/data/private-evidence','db':'/var/lib/postgresql/data'}
        result={}
        for service,identifier in ids.items():
            mounts=json.loads(inspect(identifier,'{{json .Mounts}}'))
            matches=[mount for mount in mounts if mount['Destination']==targets[service]]
            assert len(matches)==1 and matches[0]['Type']=='volume'
            result[service]=matches[0]['Name']
        return result

    def check(action,state=None):
        code=probe+'\nprint(json.dumps(main('+repr(action)+','+repr(state)+')))\n'
        result=dc('exec','-T','app','python','-',capture=True,input=code)
        return json.loads(result)

    phase='configuration'
    try:
        assert not dc('ps','--all','-q',capture=True), 'Test project name is already in use.'
        dc('config','--quiet')
        phase='build_and_seed'
        print('Building a fresh isolated PostgreSQL/app project; allow several minutes.',flush=True)
        dc('up','--detach','--build')
        healthy()
        before=containers(); named=volumes(before)
        report['images']={service:inspect(identifier,'{{.Image}}') for service,identifier in before.items()}
        initial=check('seed'); state=initial.pop('state')
        write_json(directory/'private-state.json',state)
        report['phases'].append({'name':phase,'status':'PASS',**initial})
        for phase in ('app_restart','app_container_replacement','database_restart','full_stack_replacement'):
            print('Checking '+phase+' ...',flush=True)
            previous=containers()
            if phase=='app_restart':dc('restart','app')
            elif phase=='app_container_replacement':dc('up','--detach','--no-deps','--force-recreate','app')
            elif phase=='database_restart':dc('restart','db')
            else:
                dc('down')  # Named volumes are deliberately retained; never use -v.
                dc('up','--detach')
            healthy();current=containers()
            assert volumes(current)==named, 'Named-volume identity changed.'
            if phase in ('app_container_replacement','full_stack_replacement'):
                assert current['app']!=previous['app'], 'App container was not actually replaced.'
            if phase=='full_stack_replacement':
                assert current['db']!=previous['db'], 'Database container was not actually replaced.'
            result=check('verify',state)
            report['phases'].append({'name':phase,'status':'PASS',**result})
        phase='stop_isolated_containers'
        dc('down')
        report['status']='PASS_COMPONENT_CHECKS'
        report['test_project']=project
        report['named_volumes_retained']=True
    except (AssertionError,RuntimeError,subprocess.CalledProcessError,ValueError,OSError) as error:
        report['status']='FAIL'
        report['failed_phase']=phase
        report['error_type']=type(error).__name__
        report['test_project']=project
        report['named_volumes_retained']=True
        print('The component check failed; diagnostic details remain in the isolated Docker project.',flush=True)
    report['finished_at_utc']=datetime.now(timezone.utc).isoformat()
    output=directory/'report.json';write_json(output,report)
    print(json.dumps({'status':report['status'],'passed_phases':len(report['phases']),
                      'tested_revision':REVISION,'report':str(output)}),flush=True)
    print('Keep only report.json for sharing. private.env and private-state.json contain test secrets.',flush=True)
    return 0 if report['status']=='PASS_COMPONENT_CHECKS' else 2


if __name__=='__main__':
    try: raise SystemExit(finish(BUNDLE_PATH))
    except (AssertionError,RuntimeError,subprocess.CalledProcessError,OSError) as error:
        raise SystemExit(str(error)) from None
