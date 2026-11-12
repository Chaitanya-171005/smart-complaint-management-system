"""Validate this recorded component report and its exact executable sources."""
import hashlib
import json
from pathlib import Path

REVISION = '526a0d31ea4a50f666b641839177a87e79c81f6b'
PHASES = ('build_and_seed', 'app_restart', 'app_container_replacement',
          'database_restart', 'full_stack_replacement')
COUNTS = {'Complaint': 2, 'Attachment': 2, 'IntakeReceipt': 2,
          'RoutingDecision': 2, 'ComplaintHistory': 4, 'ComplaintIdSequence': 1}


def validate(directory):
    report = json.loads((directory / 'report.json').read_bytes())
    assert report['status'] == 'PASS_COMPONENT_CHECKS'
    assert report['tested_source'] == {
        'repository': 'Chaitanya-171005/smart-complaint-management-system',
        'branch': 'feature/E03-docker-jenkins', 'revision': REVISION,
        'working_tree_dirty': False,
    }
    assert tuple(phase['name'] for phase in report['phases']) == PHASES
    snapshot = report['phases'][0]['snapshot']
    for index, phase in enumerate(report['phases']):
        assert phase['status'] == 'PASS'
        assert phase['snapshot'] == snapshot
        assert snapshot['counts'] == COUNTS
        assert snapshot['verified_evidence_files'] == 2
        assert phase['runtime']['database_vendor'] == 'postgresql'
        assert phase['runtime']['postgresql_version'] == 170006
        expected = {'successful_intake', 'concurrent_same_key', 'history_rollback',
                    'receipt_rollback', 'commit_rollback', 'storage_refusal', 'idempotent_retry'} if index == 0 else {
                    'persisted_graph_and_file_hashes', 'retry_after_restart'}
        assert set(phase['checks']) == expected
        assert all(value is True for value in phase['checks'].values())
    for field, filename in [('probe_sha256', 'probe.py'), ('driver_sha256', 'run_q05.py')]:
        assert hashlib.sha256((directory / filename).read_bytes()).hexdigest() == report[field]
    assert report['named_volumes_retained'] is True
    assert report['remaining_q05'] == ['final_merged_application',
        'PR76_crash_reconciliation_on_postgresql', 'scheduler_overlap_and_interruption',
        'auto_close_vs_feedback', 'real_notification_outbox_failures']
    return report


if __name__ == '__main__':
    validate(Path(__file__).resolve().parent)
    print('Verified: five PostgreSQL component phases, unchanged graph/evidence, exact driver/probe hashes. Final Q05 acceptance remains pending.')
