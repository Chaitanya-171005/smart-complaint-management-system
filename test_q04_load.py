"""Q04 harness correctness: real loopback HTTP, no deployed performance claims."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs

import pytest
from scripts import q04_load as q04


@pytest.fixture
def server():
    state = {"forms": 0, "posts": [], "login_hits": 0, "sources": []}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def send(self, status, content=b"", headers=None):
            self.send_response(status)
            for key, value in (headers or {}).items(): self.send_header(key, value)
            self.end_headers()
            self.wfile.write(content)
        def do_GET(self):
            state["sources"].append((self.client_address[0],self.headers.get("X-Real-IP")))
            if self.path in ('/form/', '/fixed-form/'):
                state['forms'] += 1
                token = str(state['forms']) if self.path == '/form/' else 'fixed-operation'
                self.send(200, ('<input name="csrfmiddlewaretoken" value="private-csrf">'
                               f'<input name="request_token" value="{token}">').encode(),
                          {'Set-Cookie': 'csrftoken=private-csrf; Path=/'})
            elif self.path == '/login/':
                state['login_hits'] += 1
                self.send(200, b'Please sign in')
            elif self.path == '/redirect/': self.send(302, headers={'Location':'/login/'})
            elif self.path == '/error/': self.send(503, b'Secret private server exception')
            elif self.path == '/empty/': self.send(200, b'No matching complaint was found.')
            elif self.path == '/page/': self.send(200, b'<h1>Queue</h1>'+b'<article>complaint</article>'*26)
            else:
                time.sleep(.002)
                self.send(200, b'<h1>Valid complaint detail</h1>')
        def do_POST(self):
            data = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
            state['posts'].append(data)
            assert data['csrfmiddlewaretoken'] == ['private-csrf']
            assert 'csrftoken=private-csrf' in self.headers['Cookie']
            self.send(200, b'Your complaint was submitted')
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try: yield f'http://127.0.0.1:{httpd.server_port}', state
    finally: httpd.shutdown();httpd.server_close();thread.join(timeout=5)


def case(**overrides):
    return {'name':'detail', 'path':'/detail/', 'role':'ANONYMOUS', 'method':'GET',
            'expect_pattern':'Valid complaint detail', 'threshold_ms':2000, **overrides}


def operate(server, scenario):
    origin, _ = server
    return q04.ActorClient(origin, None).operation(scenario, {}, set(), threading.Lock())


@pytest.mark.parametrize('values,fraction,expected', [([1,2,3,4],.95,4),
    (list(range(1,101)),.95,95), ([7],.5,7), ([],.95,None)])
def test_nearest_rank_percentile(values,fraction,expected):
    assert q04.percentile(values,fraction)==expected


def test_bad_response_is_never_a_fast_pass(server):
    result=operate(server,case(path='/error/'))
    assert result['status']==503 and result['error']=='unexpected_status'
    assert q04.summarize([result],2000)['status']=='FAIL'


def test_no_match_is_not_a_successful_tracking_benchmark(server):
    result=operate(server,case(name='tracking',path='/empty/',expect_pattern='SCMS-2026-000001'))
    assert result['error']=='unexpected_content'


def test_login_redirect_is_not_followed_or_counted_as_success(server):
    result=operate(server,case(path='/redirect/'))
    assert result['status']==302 and result['error']=='unexpected_status'
    assert server[1]['login_hits']==0


def test_login_redirect_cannot_be_declared_an_accepted_action(server):
    result=operate(server,case(path='/redirect/',expect_status=302,expect_pattern='.*'))
    assert result['error']=='unexpected_redirect'


def test_pagination_failure_is_reported(server):
    result=operate(server,case(path='/page/',expect_pattern='Queue',record_pattern='<article>',max_records=25))
    assert result['error']=='pagination_failed'


def test_valid_detail_has_measured_time(server):
    result=operate(server,case())
    assert not result['error'] and result['elapsed_ms']>=2
    assert q04.summarize([result],2000)['status']=='PASS'


def test_form_tokens_and_csrf_are_obtained_for_each_new_post(server):
    origin,state=server
    client=q04.ActorClient(origin,None)
    scenario=case(name='intake',method='POST',path='/submit/',prepare_path='/form/',
                  fresh_operation_token=True,expect_pattern='Your complaint was submitted')
    tokens,lock=set(),threading.Lock()
    for _ in range(2): assert not client.operation(scenario,{},tokens,lock)['error']
    assert len(state['posts'])==len(tokens)==2
    assert state['posts'][0]['request_token'] != state['posts'][1]['request_token']


def test_reused_intake_token_never_benchmarks_an_idempotent_replay(server):
    client=q04.ActorClient(server[0],None)
    scenario=case(name='intake',method='POST',path='/submit/',prepare_path='/fixed-form/',
                  fresh_operation_token=True,expect_pattern='Your complaint was submitted')
    tokens,lock=set(),threading.Lock()
    assert not client.operation(scenario,{},tokens,lock)['error']
    assert client.operation(scenario,{},tokens,lock)['error']=='missing_or_reused_operation_token'
    assert len(server[1]['posts'])==1


@pytest.mark.parametrize('change', [{'path':'https://other.example/'}, {'path':'//other.example/'},
    {'threshold_ms':2001}, {'expect_pattern':''}, {'method':'DELETE'},
    {'name':'intake','method':'POST','prepare_path':'/form/'},
    {'record_pattern':'<article>','max_records':26}])
def test_invalid_or_weakened_scenarios_are_refused(change):
    with pytest.raises(AssertionError): q04.check_case(case(**change))


def test_no_target_writes_blocked_and_returns_nonzero(tmp_path,monkeypatch):
    monkeypatch.delenv('SCMS_Q04_BASE_URL',raising=False)
    config=tmp_path/'input.json';config.write_text(json.dumps({'cases':[]}))
    output=tmp_path/'result.json'
    assert q04.main(['--config',str(config),'--output',str(output)])==2
    result=json.loads(output.read_text())
    assert result['status']=='BLOCKED' and not result['results']


def test_existing_evidence_is_not_overwritten(tmp_path,monkeypatch):
    monkeypatch.delenv('SCMS_Q04_BASE_URL',raising=False)
    config=tmp_path/'input.json';config.write_text('{}')
    output=tmp_path/'result.json';output.write_text('retained')
    with pytest.raises(FileExistsError): q04.main(['--config',str(config),'--output',str(output)])
    assert output.read_text()=='retained'


def test_fifty_users_and_iterations_are_required(tmp_path):
    config=tmp_path/'input.json';config.write_text('{"users": 1}')
    with pytest.raises(AssertionError):
        q04.main(['--config',str(config),'--output',str(tmp_path/'out.json')])


def test_distinct_authenticated_accounts_required_before_network():
    actors={'HEAD':[{'account_key':'same-user','session_cookie':'same-secret'}]*50}
    result=q04.run_case(case(role='HEAD'), 'http://127.0.0.1:1',actors,50,2,'synthetic')
    assert result['status']=='BLOCKED' and result['reason']=='distinct_test_accounts_required'


def test_action_targets_required_before_network():
    actors={'HEAD':[{'account_key':str(i),'session_cookie':str(i)} for i in range(50)]}
    scenario=case(name='action',role='HEAD',method='POST',prepare_path='/form/',threshold_ms=1500)
    result=q04.run_case(scenario,'http://127.0.0.1:1',actors,50,2,'synthetic')
    assert result['status']=='BLOCKED' and result['reason']=='distinct_prepared_action_targets_required'


def test_missing_environment_payload_is_blocked(monkeypatch):
    monkeypatch.delenv('SYNTHETIC_REFERENCE',raising=False)
    result=q04.run_case(case(payload_env={'reference':'SYNTHETIC_REFERENCE'}),
                        'http://127.0.0.1:1',{},50,2,'synthetic')
    assert result['status']=='BLOCKED' and result['reason']=='missing_payload_environment'


def test_real_worker_pool_samples_and_excludes_warmup(server):
    result=q04.run_case(case(),server[0],{},3,2,'synthetic')
    assert result['status']=='PASS' and result['requests']==6 and result['warmup_operations']==3


def test_response_secrets_are_not_in_result(server):
    result=operate(server,case(path='/error/'))
    assert 'Secret private server exception' not in json.dumps(result)
    assert 'private-csrf' not in json.dumps(result)


def test_threshold_failure_includes_all_samples():
    result=q04.summarize([{'status':200,'elapsed_ms':2100,'error':None} for _ in range(50)],2000)
    assert result['status']=='FAIL' and result['p95_ms']==2100 and result['requests']==50


@pytest.mark.parametrize('missing,pagination,status', [(True,True,'INCOMPLETE_OR_FAILED'),
    (False,False,'INCOMPLETE_OR_FAILED'),(False,True,'HTTP_CHECKS_PASS')])
def test_partial_coverage_never_becomes_a_complete_http_pass(tmp_path,monkeypatch,missing,pagination,status):
    monkeypatch.setenv('SCMS_Q04_BASE_URL','http://127.0.0.1:1')
    config=tmp_path/'input.json'
    names=q04.REQUIRED[:-1] if missing else q04.REQUIRED
    config.write_text(json.dumps({'environment':{'source_revision':'a'*40,'database_engine':'postgresql',
        'dataset_description':'Synthetic dataset','network_conditions':'Loopback unit test'},
        'cases':[{'name':name,'enabled':True,'private_value':'do-not-report'} for name in names]}))
    monkeypatch.setattr(q04,'run_case',lambda c,*args:{'name':c['name'],'status':'PASS','pagination_checked':pagination})
    output=tmp_path/'result.json'
    exit_code=q04.main(['--config',str(config),'--output',str(output)])
    report=json.loads(output.read_text())
    assert report['status']==status and exit_code==(0 if status=='HTTP_CHECKS_PASS' else 2)
    assert 'do-not-report' not in output.read_text()
    assert '5MB_upload_at_2Mbps' in report['remaining_q04_checks']



def test_optional_source_address_uses_real_socket_without_forwarding_headers(server):
    client=q04.ActorClient(server[0],{'source_address':'127.0.0.1'})
    result=client.operation(case(),{},set(),threading.Lock())
    assert not result['error'] and server[1]['sources']==[('127.0.0.1',None)]


def test_invalid_source_address_is_refused_before_network(server):
    with pytest.raises(ValueError): q04.ActorClient(server[0],{'source_address':'forged-header-value'})


def test_tracking_can_budget_nine_measured_attempts_plus_warmup(server):
    scenario=case(name='tracking',method='POST',path='/submit/',prepare_path='/form/',
                  iterations_per_user=9,expect_pattern='Your complaint was submitted')
    result=q04.run_case(scenario,server[0],{},3,10,'synthetic')
    assert result['status']=='PASS' and result['requests']==27 and result['warmup_operations']==3
    assert result['iterations_per_user']==9 and len(server[1]['posts'])==30


@pytest.mark.parametrize('name',['tracking','action'])
def test_form_get_cannot_be_counted_as_post_business_operation(name):
    with pytest.raises(AssertionError):q04.check_case(case(name=name,threshold_ms=1500))
