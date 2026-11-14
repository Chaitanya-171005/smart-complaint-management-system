import json
from pathlib import Path
import pytest
from scripts import q04_env


def test_state_paths_and_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(q04_env, 'STATE', tmp_path / 'private state')
    settings=q04_env.get_settings(True, 55019, 650)
    assert settings['project'].startswith('q04')
    assert q04_env.get_settings()['project']==settings['project']
    assert (tmp_path/'private state'/'settings.json').exists()
    if q04_env.os.name != 'nt':
        assert ((tmp_path/'private state'/'settings.json').stat().st_mode & 0o777)==0o600


def test_invalid_initial_settings_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(q04_env, 'STATE', tmp_path)
    with pytest.raises(ValueError): q04_env.get_settings(True,80,650)
    with pytest.raises(ValueError): q04_env.get_settings(True,55004,549)


def test_compose_has_loopback_and_no_public_database():
    source=q04_env.COMPOSE.read_text()
    assert '127.0.0.1:${Q04_PORT' in source
    assert 'POSTGRES_PASSWORD: ${Q04_DB_PASSWORD:?required}' in source
    assert 'ANONYMOUS_INTAKE_ENABLED: "False"' in source
    assert source.index('  app:') > source.index('  db:')
    assert 'ports:' not in source.split('  app:')[0]
    assert 'q04_database:' in source and 'q04_evidence:' in source


def test_missing_environment_refuses_start(tmp_path, monkeypatch):
    monkeypatch.setattr(q04_env, 'STATE', tmp_path)
    with pytest.raises(ValueError, match='not initialized'): q04_env.get_settings()


def test_readiness_reports_gate_and_missing_routes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(q04_env, 'STATE', tmp_path)
    actors={'HEAD':[{'session_cookie':'head'}], 'COMPLAINANT':[{'session_cookie':'complainant'}]}
    (tmp_path/'actors.json').write_text(json.dumps(actors))
    def fake_http(port,path,cookie):
        if path.startswith('/routing/queue/'): return 200, '<article>' * 25
        if path in ('/complaints/new/','/anonymous/new/'): return 503, ''
        return 404, ''
    monkeypatch.setattr(q04_env, 'http', fake_http)
    monkeypatch.setattr(q04_env, 'compose', lambda *args, **kwargs: None)
    monkeypatch.setattr(q04_env, 'release_gates', lambda _: {'intake':False,'anonymous':False})
    q04_env.check({'port':55004})
    output=capsys.readouterr().out
    assert 'queue: READY (HTTP 200, rows=25)' in output
    assert 'authenticated intake: RELEASE_GATED (HTTP 503)' in output
    assert 'tracking: ROUTE_UNAVAILABLE (HTTP 404)' in output
    assert 'evidence upload/download: NOT_VERIFIED' in output


def test_existing_configuration_cannot_change(tmp_path, monkeypatch):
    monkeypatch.setattr(q04_env, 'STATE', tmp_path)
    q04_env.get_settings(True, 55020, 650, 42)
    for args in ((55021,650,42),(55020,651,42),(55020,650,43)):
        with pytest.raises(ValueError, match='differs'):
            q04_env.get_settings(True,*args)


def test_untrusted_project_name_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(q04_env, 'STATE', tmp_path)
    (tmp_path/'settings.json').write_text(json.dumps({'project':'production','port':55004,'complaints':650}))
    with pytest.raises(ValueError,match='identity'):
        q04_env.get_settings()


def test_service_failure_not_mislabeled_as_release_gate(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(q04_env, 'STATE', tmp_path)
    (tmp_path/'actors.json').write_text(json.dumps({'HEAD':[{'session_cookie':'h'}],'COMPLAINANT':[{'session_cookie':'c'}]}))
    monkeypatch.setattr(q04_env,'release_gates',lambda _: {'intake':True,'anonymous':True})
    monkeypatch.setattr(q04_env,'http',lambda *args:(503,''))
    monkeypatch.setattr(q04_env,'compose',lambda *args, **kwargs: None)
    q04_env.check({'port':55004})
    assert 'authenticated intake: FAILED (HTTP 503)' in capsys.readouterr().out


def test_conflict_message_has_only_nonsecret_values(tmp_path, monkeypatch):
    monkeypatch.setattr(q04_env,'STATE',tmp_path)
    q04_env.get_settings(True,55017,650,0)
    with pytest.raises(ValueError,match='existing=0, requested=42'):
        q04_env.get_settings(True,55017,650,42)


def test_lock_excludes_second_operation(tmp_path, monkeypatch):
    monkeypatch.setattr(q04_env,'STATE',tmp_path)
    with q04_env.environment_lock():
        with pytest.raises(ValueError,match='Another Q04'):
            with q04_env.environment_lock(): pass
    with q04_env.environment_lock(): pass


def test_reset_volume_ownership_mismatch_refused(monkeypatch):
    class Result:
        stdout=json.dumps([{'Labels':{'com.docker.compose.project':'other','com.docker.compose.volume':'q04_database'}}])
    def inspect(argv,**kwargs):
        result=Result()
        if argv[2]=='ls': result.stdout='q04abcdef123456_q04_database\nq04abcdef123456_q04_evidence\n'
        return result
    monkeypatch.setattr(q04_env,'invoke',inspect)
    with pytest.raises(ValueError,match='ownership mismatch'):
        q04_env.verify_volume_ownership({'project':'q04abcdef123456'})


def test_reset_volume_ownership_correct(monkeypatch):
    def inspect(argv,**kwargs):
        if argv[2]=='ls':
            class Result: stdout='q04abcdef123456_q04_database\nq04abcdef123456_q04_evidence\n'
            return Result()
        name=argv[-1].split('_')[-1]
        kind='q04_'+name
        class Result: pass
        result=Result(); result.stdout=json.dumps([{'Labels':{'com.docker.compose.project':'q04abcdef123456','com.docker.compose.volume':kind}}])
        return result
    monkeypatch.setattr(q04_env,'invoke',inspect)
    q04_env.verify_volume_ownership({'project':'q04abcdef123456'})


def test_recovery_only_allows_preflight(tmp_path, monkeypatch):
    monkeypatch.setattr(q04_env,'STATE',tmp_path)
    marker=tmp_path/'action-targets-consumed'
    marker.write_text('running')
    with pytest.raises(ValueError,match='preflight'):
        q04_env.recover_preflight()
    assert marker.read_text()=='running'
    marker.write_text('preflight')
    q04_env.recover_preflight()
    assert not marker.exists()


def test_run_state_persists_identifier_and_phases(tmp_path, monkeypatch):
    monkeypatch.setattr(q04_env,'STATE',tmp_path)
    marker=tmp_path/'action-targets-consumed'
    record={'run_id':'test-id'}
    q04_env.write_run_state(marker,record,'preflight','preflight')
    assert json.loads(marker.read_text())['run_id']=='test-id'
    q04_env.write_run_state(marker,record,'interrupted','preflight')
    q04_env.recover_preflight()
    assert not marker.exists()
    q04_env.write_run_state(marker,record,'interrupted','execution')
    with pytest.raises(ValueError,match='preflight'): q04_env.recover_preflight()
    assert json.loads(marker.read_text())['state']=='interrupted'


def test_sessions_invalid_on_expiry_or_role_change(tmp_path,monkeypatch):
    monkeypatch.setattr(q04_env,'STATE',tmp_path)
    entries=lambda prefix:[{'session_cookie':f'{prefix}{i}'} for i in range(50)]
    (tmp_path/'actors.json').write_text(json.dumps({'HEAD':entries('h'),'COMPLAINANT':entries('c')}))
    monkeypatch.setattr(q04_env,'http',lambda port,path,cookie:(302,'') if cookie=='h0' else (200,'Q04 synthetic complaint'))
    assert not q04_env.sessions_valid({'port':1234,'complaints':650})
    monkeypatch.setattr(q04_env,'http',lambda port,path,cookie:(200,'Q04 synthetic complaint'))
    assert not q04_env.sessions_valid({'port':1234,'complaints':650})


def test_lifecycle_lock_excludes_separate_process(tmp_path, monkeypatch):
    import subprocess, sys
    monkeypatch.setattr(q04_env,'STATE',tmp_path)
    script="from pathlib import Path; import sys; from scripts import q04_env as q; q.STATE=Path(sys.argv[1]);\nwith q.environment_lock(): print('acquired')"
    with q04_env.environment_lock():
        result=subprocess.run([sys.executable,'-c',script,str(tmp_path)],capture_output=True,text=True)
        assert result.returncode != 0
        assert 'Another Q04 operation is running' in result.stderr
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path)],capture_output=True,text=True)
    assert result.returncode == 0 and result.stdout.strip() == 'acquired'


def test_unknown_or_execution_run_reservation_cannot_recover(tmp_path, monkeypatch):
    monkeypatch.setattr(q04_env,'STATE',tmp_path)
    marker=tmp_path/'action-targets-consumed'
    for text in ('', 'running', '{bad', json.dumps({'state':'failed','phase':'execution'}),json.dumps({'state':'completed','phase':'execution'})):
        marker.write_text(text)
        with pytest.raises(ValueError): q04_env.recover_preflight()
        assert marker.read_text()==text


def test_sqlite_sidecars_excluded_from_docker_context():
    ignored=(q04_env.ROOT/'.dockerignore').read_text()
    for pattern in ('*.sqlite3-journal','*.sqlite3-wal','*.sqlite3-shm'):
        assert pattern in ignored


def test_missing_volume_labels_refuse_reset(monkeypatch):
    class Result: stdout=json.dumps([{'Labels':None}])
    def inspect(argv,**kwargs):
        result=Result()
        if argv[2]=='ls': result.stdout='q04abcdef123456_q04_database\nq04abcdef123456_q04_evidence\n'
        return result
    monkeypatch.setattr(q04_env,'invoke',inspect)
    with pytest.raises(ValueError,match='ownership mismatch'):
        q04_env.verify_volume_ownership({'project':'q04abcdef123456'})


def test_reset_refuses_wrong_project_without_docker_mutation(tmp_path,monkeypatch):
    import argparse
    monkeypatch.setattr(q04_env,'STATE',tmp_path)
    monkeypatch.setattr(q04_env.shutil,'which',lambda _: '/usr/bin/docker')
    monkeypatch.setattr(q04_env,'get_settings',lambda *args:{'project':'q04abcdef123456'})
    monkeypatch.setattr(q04_env,'compose',lambda *args,**kwargs: pytest.fail('must not mutate'))
    args=argparse.Namespace(command='reset',port=None,complaints=None,random_seed=None,confirm=True,project='q04ffffffffffff',environment='default')
    with pytest.raises(ValueError,match='exact --project'):
        q04_env.execute(args)


def test_competing_preflights_make_only_one_reservation(tmp_path):
    import subprocess, sys
    source = '''
from pathlib import Path
from argparse import Namespace
import sys,time
import scripts.q04_env as q
q.STATE=Path(sys.argv[1]);q.shutil.which=lambda _: 'docker'
q.get_settings=lambda *a: {'project':'q04abcdef123456'}
def preflight(*args): time.sleep(1)
q.run_preflight_and_execute=preflight
args=Namespace(command='run',port=None,complaints=None,random_seed=None,confirm=True,project=None,environment='default')
try:
    with q.environment_lock(): q.execute(args)
    print('won')
except ValueError: print('refused')
'''
    processes=[subprocess.Popen([sys.executable,'-c',source,str(tmp_path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
    results=[p.communicate(timeout=10) for p in processes]
    assert sorted(out.strip() for out,err in results)==['refused','won'], results
    record=json.loads((tmp_path/'action-targets-consumed').read_text())
    assert record['state']=='preflight' and record['run_id']


def test_potentially_mutating_reservation_blocks_reset(tmp_path,monkeypatch):
    from argparse import Namespace
    monkeypatch.setattr(q04_env,'STATE',tmp_path)
    monkeypatch.setattr(q04_env.shutil,'which',lambda _: 'docker')
    monkeypatch.setattr(q04_env,'get_settings',lambda *a:{'project':'q04abcdef123456'})
    monkeypatch.setattr(q04_env,'compose',lambda *a,**k:pytest.fail('reset must not run'))
    marker=tmp_path/'action-targets-consumed'
    q04_env.write_run_state(marker,{'run_id':'simulated'},'interrupted','execution')
    args=Namespace(command='reset',port=None,complaints=None,random_seed=None,confirm=True,project='q04abcdef123456',environment='default')
    with pytest.raises(ValueError,match='reservation'):
        q04_env.execute(args)
    with pytest.raises(ValueError,match='preflight'):
        q04_env.recover_preflight()
    assert marker.exists()


def synthetic_actor_fixture():
    heads=[]
    for i in range(50):
        operations=[{'path':f'/complaints/SCMS-2099-{i*11+j+1:06d}/assign/','payload':{'expected_assignee':''}} for j in range(11)]
        heads.append({'session_cookie':f'head-{i}','operations':{'action':operations}})
    return {'HEAD':heads,'COMPLAINANT':[{'session_cookie':f'complainant-{i}'} for i in range(50)]}


def test_preflight_rejects_exhausted_targets_without_run(tmp_path,monkeypatch):
    monkeypatch.setattr(q04_env,'STATE',tmp_path)
    (tmp_path/'actors.json').write_text(json.dumps(synthetic_actor_fixture()))
    monkeypatch.setattr(q04_env,'http',lambda port,path,cookie:(403,'') if cookie.startswith('complainant') else (200,'Q04 synthetic complaint'))
    class Result: stdout='549\n'
    monkeypatch.setattr(q04_env,'compose',lambda *a,**k:Result())
    monkeypatch.setattr(q04_env,'invoke',lambda *a,**k:pytest.fail('must not launch runner'))
    with pytest.raises(ValueError,match='consumed or unavailable'):
        q04_env.run_preflight_and_execute({'port':12345,'complaints':650},tmp_path/'marker',{'phase':'preflight'})


@pytest.mark.parametrize('bad_cookie,bad_status',[('complainant-0',302),('complainant-0',200),('head-0',302),('head-0',403)])
def test_preflight_rejects_invalid_expired_or_wrong_role_sessions(tmp_path,monkeypatch,bad_cookie,bad_status):
    monkeypatch.setattr(q04_env,'STATE',tmp_path)
    (tmp_path/'actors.json').write_text(json.dumps(synthetic_actor_fixture()))
    def fake_http(port,path,cookie):
        if cookie==bad_cookie:return bad_status,''
        return (403,'') if cookie.startswith('complainant') else (200,'Q04 synthetic complaint')
    monkeypatch.setattr(q04_env,'http',fake_http)
    monkeypatch.setattr(q04_env,'compose',lambda *a,**k:pytest.fail('must reject before database'))
    with pytest.raises(ValueError,match='session'):
        q04_env.run_preflight_and_execute({'port':12345,'complaints':650},tmp_path/'marker',{'phase':'preflight'})


@pytest.mark.parametrize('phase,recoverable',[('preflight',True),('execution',False)])
def test_interrupted_run_is_recorded_and_recovery_is_phase_bound(tmp_path,monkeypatch,phase,recoverable):
    from argparse import Namespace
    monkeypatch.setattr(q04_env,'STATE',tmp_path)
    monkeypatch.setattr(q04_env.shutil,'which',lambda _: 'docker')
    monkeypatch.setattr(q04_env,'get_settings',lambda *args:{'project':'q04abcdef123456'})
    def interrupt(data,marker,record):
        if phase=='execution':q04_env.write_run_state(marker,record,'running','execution')
        raise KeyboardInterrupt()
    monkeypatch.setattr(q04_env,'run_preflight_and_execute',interrupt)
    args=Namespace(command='run',port=None,complaints=None,random_seed=None,confirm=True,project=None,environment='default')
    with pytest.raises(KeyboardInterrupt):q04_env.execute(args)
    marker=tmp_path/'action-targets-consumed'
    assert json.loads(marker.read_text())['state']=='interrupted'
    if recoverable:
        q04_env.recover_preflight()
        assert not marker.exists()
        with pytest.raises(ValueError):q04_env.recover_preflight()
    else:
        for _ in range(2):
            with pytest.raises(ValueError):q04_env.recover_preflight()
        assert marker.exists()


def test_reset_rejects_unexpected_project_volumes(monkeypatch):
    class Result: stdout='q04abcdef123456_q04_database\nq04abcdef123456_q04_evidence\nq04abcdef123456_extra\n'
    monkeypatch.setattr(q04_env,'invoke',lambda *a,**k:Result())
    with pytest.raises(ValueError,match='Unexpected or missing'):
        q04_env.verify_volume_ownership({'project':'q04abcdef123456'})
