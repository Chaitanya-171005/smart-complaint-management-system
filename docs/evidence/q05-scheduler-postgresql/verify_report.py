"""Validate the recorded scheduler component report, harness hashes and case list."""
import hashlib
import json
from pathlib import Path

CASES = {
    'test_two_processes_compete_for_same_due_complaint',
    'test_repeated_runs_respect_interval_and_maximum',
    'test_sigkill_then_retry_preserves_one_escalation[before_commit]',
    'test_sigkill_then_retry_preserves_one_escalation[after_commit]',
    'test_required_history_failure_rolls_back_then_retries',
    'test_callback_failure_keeps_commit_and_retry_does_not_duplicate',
}


def validate(directory):
    report = json.loads((directory/'report.json').read_bytes())
    assert hashlib.sha256((directory/'report.json').read_bytes()).hexdigest() == '668b4220ea9cff4746138b7f7fda98057b433027f7e0d2e4b6e6fe605230c2ef'
    assert report['status'] == 'PASS_BUSINESS_RECOVERY_CHECKS'
    assert (report['executed_cases'],report['skipped'],report['failed_or_errored'],report['pytest_exit_code']) == (6,0,0,0)
    assert report['runtime']['database_vendor'] == 'postgresql' and report['runtime']['postgresql_version'] == 170006
    assert report['application_working_tree_dirty'] is False
    assert report['application_tree'] == 'ae0723f2a34ffbb932b7c6dd2ea5b81e1616f4a3'
    assert report['parents'] == {'B18':'2a0697bbbf88a6ca8d67a64ecb69a466897e7bd8','Main':'ebc8ffdf9c1ae37365fad71c084869c73a35b4d0'}
    for name,digest in report['harness_sha256'].items():
        assert hashlib.sha256((directory/'sources'/(name+'.txt')).read_bytes()).hexdigest() == digest
    for field,name in [('driver_sha256','run_task.py.txt'),('dockerfile_sha256','Dockerfile')]:
        assert hashlib.sha256((directory/'sources'/name).read_bytes()).hexdigest() == report[field]
    assert report['remaining_q05'] == ['stale_RUNNING_records_after_SIGKILL_need_supervision',
        'real_scheduler_deployment','actual_F4_notification_outbox_delivery','auto_close_vs_feedback',
        'final_merged_deployment_validation']
    summary = json.loads((directory/'case-results.json').read_text())
    assert len(summary['cases']) == 6 and {case['name'] for case in summary['cases']} == CASES
    assert all(case['outcome'] == 'passed' and case['time_seconds'] >= 0 for case in summary['cases'])
    assert len(summary['source_junit_sha256']) == 64
    return report


if __name__ == '__main__':
    validate(Path(__file__).resolve().parent)
    print('Verified six PostgreSQL scheduler business-recovery cases; abandoned-run supervision and final Q05 acceptance remain pending.')
