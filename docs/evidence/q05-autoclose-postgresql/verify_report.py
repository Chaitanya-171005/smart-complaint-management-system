"""Validate the recorded auto-close/feedback component report, harness hashes and case list."""
import hashlib
import json
from pathlib import Path



def validate(directory):
    report = json.loads((directory/'report.json').read_bytes())
    assert hashlib.sha256((directory/'report.json').read_bytes()).hexdigest() == 'a9a62d0c4e06c18cb97d63682d060f1928a30d1666c934c227acbac86b3b654d'
    assert report['status'] == 'PASS_LIFECYCLE_COMPONENT_CHECKS'
    assert (report['executed_cases'],report['skipped'],report['failed_or_errored'],report['pytest_exit_code']) == (125,0,0,0)
    assert report['runtime']['database_vendor'] == 'postgresql' and report['runtime']['postgresql_version'] == 170006
    assert report['application_working_tree_dirty'] is False
    assert report['application_tree'] == '65fd8cf0d2b657d780cc94df830c5bd5a82085c0'
    assert report['parents'] == {'F4_PR78': '0a8ddc9db486de97bc010603f5b9124a8c26e200', 'Main': 'ebc8ffdf9c1ae37365fad71c084869c73a35b4d0'}
    for name,digest in report['harness_sha256'].items():
        assert hashlib.sha256((directory/'sources'/(name+'.txt')).read_bytes()).hexdigest() == digest
    for field,name in [('driver_sha256','run_task.py.txt'),('dockerfile_sha256','Dockerfile')]:
        assert hashlib.sha256((directory/'sources'/name).read_bytes()).hexdigest() == report[field]
    assert report['policy'] == {'COMPLAINT_AUTO_CLOSE_DAYS': 7, 'approval': 'PROPOSED_TEST_SETTING_ONLY'}
    summary = json.loads((directory/'case-results.json').read_text())
    assert len(summary['cases']) == 125
    assert sorted(case['id'] for case in summary['cases']) == json.loads((directory/'expected-cases.json').read_text())
    assert all(case['outcome'] == 'passed' and case['time_seconds'] >= 0 for case in summary['cases'])
    assert len(summary['source_junit_sha256']) == 64
    return report


if __name__ == '__main__':
    validate(Path(__file__).resolve().parent)
    print('Verified 125 PostgreSQL lifecycle component cases; policy, scheduler, SMTP delivery and final Q05 acceptance remain pending.')
