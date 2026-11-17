"""Verify pinned Q05 SMTP component evidence; no external mail/deployment claim."""
import hashlib
import json
import math
from pathlib import Path


def validate(directory):
    raw=(directory/'report.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='6622916faf168776915cff8c86f85ad1cfdd3371d335be09e988817cf1e73d0d'
    report=json.loads(raw)
    assert report['repository']=='Chaitanya-171005/smart-complaint-management-system'
    assert report['source_revision']=='9b163a24985406d4c00f993bbf2b58e8080cd983'
    assert report['source_pins']=={'F4_PR78':report['source_revision']}
    assert report['dependency_PR77']=='cda6fc5e05946d75999ee4f91dd723d571c348a0'
    assert report['application_tree']=='373d40579d5e96f726990b202dd6c5be6ff04056'
    assert report['application_working_tree_dirty'] is False
    assert report['status']=='PASS_SMTP_RECOVERY_COMPONENT_CHECKS'
    assert (report['executed_cases'],report['skipped'],report['failed_or_errored'],report['pytest_exit_code'])==(19,0,0,0)
    assert report['runtime']=={'database_vendor':'postgresql','postgresql_version':170006,'python_version':'3.14.10','django_version':'6.1.3'}
    for name,digest in report['harness_sha256'].items():
        assert hashlib.sha256((directory/'sources'/(name+'.txt')).read_bytes()).hexdigest()==digest
    for field,name in [('driver_sha256','run_task.py.txt'),('dockerfile_sha256','Dockerfile')]:
        assert hashlib.sha256((directory/'sources'/name).read_bytes()).hexdigest()==report[field]
    expected=json.loads((directory/'expected-cases.json').read_text())
    assert len(expected)==len(set(expected))==19
    reported={case['classname']+'::'+case['name']:float(case['seconds']) for case in report['case_results']}
    assert sorted(reported)==expected
    summary=json.loads((directory/'case-results.json').read_text())
    assert summary['source_junit_sha256']==report['junit_sha256']
    assert sorted(case['id'] for case in summary['cases'])==expected
    for case in summary['cases']:
        assert case['outcome']=='passed'
        assert math.isfinite(case['time_seconds']) and case['time_seconds']>=0
        assert case['time_seconds']==reported[case['id']]
    assert len(report['remaining_q05'])==6
    return report


if __name__=='__main__':
    validate(Path(__file__).resolve().parent)
    print('Verified 19 PostgreSQL/loopback SMTP component cases. Final integration, external delivery and deployment acceptance remain pending.')
