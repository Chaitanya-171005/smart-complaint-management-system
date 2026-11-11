"""Q05 synthetic graph checks executed inside the pinned E03 application image."""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','scms.settings')
import django
django.setup()
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
from pathlib import Path
import threading
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, close_old_connections, connection
from PIL import Image
from accounts.models import Department, Location, User
from complaints import submission
from complaints.evidence import PrivateEvidenceStorage
from complaints.intake import new_intake_key
from complaints.models import Attachment, Complaint, ComplaintIdSequence, IntakeReceipt
from routing.models import Category, EscalationPolicy, RoutingDecision, RoutingRule, SLAConfiguration
from workflow.models import ComplaintHistory

MODELS=(Complaint,Attachment,IntakeReceipt,RoutingDecision,ComplaintHistory,ComplaintIdSequence)


def upload():
    stream=BytesIO()
    Image.new('RGB',(3,3),'red').save(stream,format='PNG')
    return SimpleUploadedFile('synthetic-q05.png',stream.getvalue(),content_type='image/png')


def snapshot():
    rows={model.__name__:list(model.objects.order_by('pk').values()) for model in MODELS}
    root=Path(settings.PRIVATE_EVIDENCE_ROOT)
    actual={item.name:item for item in root.iterdir()} if root.exists() else {}
    attachments=list(Attachment.objects.order_by('pk'))
    assert set(actual)=={item.storage_name for item in attachments}, 'Unexpected/missing private evidence file.'
    for attachment in attachments:
        path=actual[attachment.storage_name]
        assert path.is_file() and not path.is_symlink()
        data=path.read_bytes()
        assert len(data)==attachment.size and hashlib.sha256(data).hexdigest()==attachment.sha256
    digest=hashlib.sha256(json.dumps(rows,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
    return {'counts':{name:len(items) for name,items in rows.items()},
            'graph_sha256':digest,'verified_evidence_files':len(attachments)}


def submit(state,key=None):
    return submission.submit_authenticated_complaint(user=User.objects.get(pk=state['user_id']),
        key=key or state['key'],data=state['data'],files=[upload()])


def seed():
    assert all(not model.objects.exists() for model in MODELS), 'Use a fresh disposable project/database.'
    assert not list(Path(settings.PRIVATE_EVIDENCE_ROOT).glob('*')), 'Use a fresh disposable evidence volume.'
    suffix=uuid4().hex[:12]
    department=Department.objects.create(name='Synthetic Q05 '+suffix)
    category=Category.objects.create(name='Synthetic Q05 '+suffix)
    location=Location.objects.create(code='Q05-'+suffix.upper(),block='Synthetic Q05',floor='1',room_area='Persistence test')
    RoutingRule.objects.create(category=category,location_code=location.code,department=department,precedence=1)
    SLAConfiguration.objects.create(category=category,priority='LOW',duration_minutes=120)
    policy=EscalationPolicy.objects.filter(key='default').first() or EscalationPolicy(key='default')
    policy.default_department=department
    policy.interval_minutes=120
    policy.maximum_level=2
    policy.full_clean();policy.save()
    user=User.objects.create_user(email='q05-'+suffix+'@example.test',password=None,
                                  full_name='Synthetic Q05 User',role=User.Role.COMPLAINANT)
    state={'user_id':user.pk,'key':new_intake_key(),'data':{'category':str(category.pk),'location':location.code,
        'title':'Synthetic Q05 persistence test','description':'Synthetic validation record, not a real campus incident.',
        'priority':'LOW','sub_category':''}}
    first=submit(state)
    assert not first.replayed
    state['complaint_id']=first.complaint_id
    concurrent_key=new_intake_key()
    barrier=threading.Barrier(2)
    def accept(_):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return submit(state,concurrent_key)
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(accept,range(2)))
    assert sorted(item.replayed for item in results)==[False,True]
    assert len({item.complaint_id for item in results})==1
    expected=snapshot()
    assert expected['counts']=={'Complaint':2,'Attachment':2,'IntakeReceipt':2,
        'RoutingDecision':2,'ComplaintHistory':4,'ComplaintIdSequence':1}
    for target,error in [('history',RuntimeError),('receipt',RuntimeError),('commit',IntegrityError),('storage',OSError)]:
        if target=='history':
            original=submission.record_history
            def fail_second(*args,**kwargs):
                if args[1]=='ALLOCATED': raise RuntimeError('Synthetic Q05 injected failure')
                return original(*args,**kwargs)
            failure=patch.object(submission,'record_history',side_effect=fail_second)
        elif target=='receipt': failure=patch.object(IntakeReceipt.objects,'create',side_effect=RuntimeError('Synthetic Q05 failure'))
        elif target=='commit': failure=patch.object(connection,'commit',side_effect=IntegrityError('Synthetic Q05 failure'))
        else: failure=patch.object(PrivateEvidenceStorage,'save',side_effect=OSError('Synthetic Q05 failure'))
        caught=False
        with failure:
            try: submit(state,new_intake_key())
            except error: caught=True
        assert caught, 'Required injected failure did not propagate.'
        assert snapshot()==expected, 'Failure changed accepted rows/identifiers/evidence.'
    replay=submit(state)
    assert replay.replayed and replay.complaint_id==state['complaint_id']
    assert snapshot()==expected
    state['expected_snapshot']=expected
    return {'state':state,'snapshot':expected,'checks':{'successful_intake':True,'concurrent_same_key':True,
        'history_rollback':True,'receipt_rollback':True,'commit_rollback':True,'storage_refusal':True,'idempotent_retry':True}}


def verify(state):
    assert snapshot()==state['expected_snapshot'], 'Persisted graph or evidence changed.'
    replay=submit(state)
    assert replay.replayed and replay.complaint_id==state['complaint_id']
    current=snapshot()
    assert current==state['expected_snapshot'], 'Retry duplicated or changed persisted data.'
    return {'snapshot':current,'checks':{'persisted_graph_and_file_hashes':True,'retry_after_restart':True}}


def main(action,state=None):
    assert connection.vendor=='postgresql', 'This acceptance check requires actual PostgreSQL.'
    assert Path(settings.PRIVATE_EVIDENCE_ROOT).resolve()==Path('/data/private-evidence')
    connection.ensure_connection()
    if action=='seed': result=seed()
    elif action=='verify': result=verify(state)
    else: raise ValueError('Unknown check action.')
    result['runtime']={'database_vendor':connection.vendor,'postgresql_version':connection.pg_version,
                       'python_version':__import__('platform').python_version(),'django_version':django.get_version()}
    return result
