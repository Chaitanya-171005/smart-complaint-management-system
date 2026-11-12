"""Explicit B11/B12 + merged B10 anonymous process-crash/lease checks.

Uses real files, real child processes and the active pytest database. A repeated
anonymous submission never recovers a previously returned raw reference.
"""
import base64
import json
import select
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.files.base import ContentFile

from complaints.anonymous import submit_anonymous_complaint
from complaints.evidence_recovery import EvidenceRecoveryUnavailable, reconcile_evidence
from complaints.models import AnonymousIntakeReceipt, Attachment, Complaint, ComplaintIdSequence, IntakeReceipt
from complaints.test_evidence_recovery import child_environment, png
from routing.models import RoutingDecision
from workflow.models import ComplaintHistory

pytestmark = pytest.mark.django_db(transaction=True)
GRAPH = (Complaint, Attachment, AnonymousIntakeReceipt, IntakeReceipt, RoutingDecision,
         ComplaintHistory, ComplaintIdSequence)


def graph():
    return {model.__name__:list(model.objects.order_by('pk').values()) for model in GRAPH}


def inputs(config):
    return {'category':str(config['category'].pk),'location':config['location'].code,
        'title':'Synthetic anonymous recovery','description':'Synthetic anonymous interrupted intake description.',
        'priority':'LOW'}


CHILD = r'''
import base64, json, os, signal, sys
from contextlib import contextmanager
import django
from django.conf import settings
settings.DATABASES = {'default':json.loads(os.environ['SCMS_TEST_DATABASE'])}
django.setup()
from django.core.files.base import ContentFile
from complaints import anonymous, evidence
mode = os.environ['SCMS_ANONYMOUS_CRASH_POINT']
original = evidence.staged_evidence
@contextmanager
def staged(files,**kwargs):
    assert kwargs.get('anonymous') is True
    with original(files,**kwargs) as batch:
        if mode == 'before': os.kill(os.getpid(),signal.SIGKILL)
        if mode == 'lease':
            print('ready',flush=True)
            if sys.stdin.readline().strip() != 'finish':raise RuntimeError('Missing test release')
        yield batch
        if mode == 'after': os.kill(os.getpid(),signal.SIGKILL)
anonymous.staged_evidence = staged
if mode == 'during':
    create = anonymous.AnonymousIntakeReceipt.objects.create
    def interrupted_create(**kwargs):
        create(**kwargs)
        os.kill(os.getpid(),signal.SIGKILL)
    anonymous.AnonymousIntakeReceipt.objects.create = interrupted_create
anonymous.submit_anonymous_complaint(key='a'*64,data=json.loads(os.environ['SCMS_TEST_FIELDS']),
    files=[ContentFile(base64.b64decode(os.environ['SCMS_TEST_PNG']),name='synthetic.png')])
assert mode == 'lease', 'Crash point was not reached'
'''


def environment(root,config,point):
    env=child_environment(root)
    env.update(SCMS_ANONYMOUS_CRASH_POINT=point,SCMS_TEST_FIELDS=json.dumps(inputs(config)),
        SCMS_TEST_PNG=base64.b64encode(png()).decode())
    return env


@pytest.mark.parametrize('point',['before','during','after'])
def test_anonymous_sigkill_recovery_and_reference_safe_retry(settings,tmp_path,routing_configuration,point):
    root=tmp_path/'private';settings.PRIVATE_EVIDENCE_ROOT=root
    before=graph()
    process=subprocess.run([sys.executable,'-c',CHILD],env=environment(root,routing_configuration,point),
        cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=25)
    assert process.returncode == -signal.SIGKILL,process.stderr
    recovered=reconcile_evidence(apply=True)
    if point == 'after':
        assert recovered.referenced == 1 and recovered.orphaned == 0
        complaint=Complaint.objects.get()
        assert complaint.submitted_by_id is None and len(complaint.reference_digest)==64
        assert AnonymousIntakeReceipt.objects.count()==Attachment.objects.count()==1
        accepted=graph()
    else:
        assert recovered.referenced == 0 and recovered.orphaned == 1
        assert graph()==before
    result=submit_anonymous_complaint(key='a'*64,data=inputs(routing_configuration),
        files=[ContentFile(png(),name='synthetic.png')])
    assert result.replayed is (point=='after')
    assert (result.reference is None) is (point=='after')
    if point=='after':assert graph()==accepted
    complaint=Complaint.objects.get()
    assert complaint.submitted_by_id is None and len(complaint.reference_digest)==64
    assert Attachment.objects.count()==AnonymousIntakeReceipt.objects.count()==1
    assert IntakeReceipt.objects.count()==0 and RoutingDecision.objects.count()==1
    assert ComplaintHistory.objects.count()==2 and ComplaintIdSequence.objects.count()==1
    attachment=Attachment.objects.get()
    assert (root/attachment.storage_name).is_file()
    assert reconcile_evidence().referenced==1
    accepted=graph()
    replay=submit_anonymous_complaint(key='a'*64,data=inputs(routing_configuration),
        files=[ContentFile(png(),name='synthetic.png')])
    assert replay.replayed and replay.reference is None and graph()==accepted
    assert reconcile_evidence(apply=True).orphaned==0


def test_anonymous_writer_holds_recovery_lease_through_commit(settings,tmp_path,routing_configuration):
    root=tmp_path/'private';settings.PRIVATE_EVIDENCE_ROOT=root
    process=subprocess.Popen([sys.executable,'-c',CHILD],env=environment(root,routing_configuration,'lease'),
        cwd=Path(__file__).resolve().parents[1],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,text=True)
    try:
        ready,_,_=select.select([process.stdout],[],[],15)
        assert ready and process.stdout.readline().strip()=='ready'
        with pytest.raises(EvidenceRecoveryUnavailable,match='active'):
            reconcile_evidence(apply=True)
        assert not Complaint.objects.exists()
        stdout,stderr=process.communicate('finish\n',timeout=25)
        assert process.returncode==0,stderr
        assert stdout==''  # Child never prints the raw reference.
    finally:
        if process.poll() is None:
            process.kill();process.communicate(timeout=5)
    assert Complaint.objects.get().submitted_by_id is None
    assert AnonymousIntakeReceipt.objects.count()==1
    assert reconcile_evidence().referenced==1
