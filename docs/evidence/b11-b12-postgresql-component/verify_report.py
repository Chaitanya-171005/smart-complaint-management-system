"""Verify recorded anonymous/privacy PostgreSQL evidence, source, hashes and case identities."""
import hashlib
import json
import math
from pathlib import Path


def validate(directory):
    raw=(directory/'report.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='ab1a9985ec2e5074ea533679de8f85b7da733da42d55ca65b6c330c26d35e373'
    report=json.loads(raw)
    assert report['repository']=='Chaitanya-171005/smart-complaint-management-system'
    assert report['source_revision']=='e91c9a1fe719209ed9fcc235b2a244eedcfc59b8'
    assert report['source_pins']=={'B11_PR71':report['source_revision']}
    assert report['included_Main']=='5c375e7da1ae43a4bfaf4972528f1ae2e79d928e'
    assert report['application_tree']=='026e517d812371650e89011cba97257fd13e60bf'
    assert report['application_working_tree_dirty'] is False
    assert report['status']=='PASS_ANONYMOUS_POSTGRESQL_COMPONENT_CHECKS'
    assert (report['executed_cases'],report['skipped'],report['failed_or_errored'],report['pytest_exit_code'])==(171,0,0,0)
    assert report['runtime']=={'database_vendor':'postgresql','postgresql_version':170006,'python_version':'3.14.10','django_version':'6.1.3'}
    for name,digest in report['harness_sha256'].items():
        assert hashlib.sha256((directory/'sources'/(name+'.txt')).read_bytes()).hexdigest()==digest
    for field,name in [('driver_sha256','run_task.py.txt'),('dockerfile_sha256','Dockerfile')]:
        assert hashlib.sha256((directory/'sources'/name).read_bytes()).hexdigest()==report[field]
    expected=json.loads((directory/'expected-cases.json').read_text())
    assert len(expected)==len(set(expected))==171
    reported={case['classname']+'::'+case['name']:float(case['seconds']) for case in report['case_results']}
    assert sorted(reported)==expected
    summary=json.loads((directory/'case-results.json').read_text())
    assert summary['source_junit_sha256']==report['junit_sha256']
    assert sorted(case['id'] for case in summary['cases'])==expected
    for case in summary['cases']:
        assert case['outcome']=='passed'
        assert math.isfinite(case['time_seconds']) and case['time_seconds']>=0
        assert case['time_seconds']==reported[case['id']]
    assert report['exact_case_ids_match'] is True
    assert len(report['remaining_acceptance'])==6
    return report


if __name__=='__main__':
    validate(Path(__file__).resolve().parent)
    print('Verified 171 anonymous/privacy/evidence PostgreSQL cases. D01/D02, F3/F4 integration and deployed privacy acceptance remain pending.')
