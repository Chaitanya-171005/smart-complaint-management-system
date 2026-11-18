"""Run inside the disposable app via manage.py shell; private JSON on stdin.

Creates/replays an authenticated aggregate through the real service, with PNG
evidence. HTTP release gates remain disabled. Emits hashes/counts, never the key.
The coordinator compares snapshots across actual app restart and replacement.
"""
import hashlib
from io import BytesIO
import json
import sys
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.serializers.json import DjangoJSONEncoder
from PIL import Image
from accounts.models import User
from complaints.submission import submit_authenticated_complaint
from complaints.evidence import PrivateEvidenceStorage
from complaints.models import Attachment, Complaint, IntakeReceipt
from routing.models import Category, RoutingDecision
from workflow.models import ComplaintHistory, NotificationEvent, Notification, EmailDelivery

spec=json.load(sys.stdin)
user=User.objects.get(email='q04-complainant-001@q04.invalid')
data={'category':str(Category.objects.get(name='Q04 Synthetic Category').pk),
      'location':'Q04-TEST','title':'Q05 local persistence probe',
      'description':'Synthetic evidence persistence and retry acceptance probe.',
      'priority':'LOW','sub_category':''}
buffer=BytesIO();Image.new('RGB',(2,2),'red').save(buffer,format='PNG')
result=submit_authenticated_complaint(user=user,key=spec['key'],data=data,
    files=[SimpleUploadedFile('evidence.png',buffer.getvalue(),content_type='image/png')])
complaint=Complaint.objects.get(complaint_id=result.complaint_id)
attachment=Attachment.objects.get(complaint=complaint)
storage=PrivateEvidenceStorage()
with storage.open(attachment.storage_name,'rb') as f:
    actual_hash=hashlib.sha256(f.read()).hexdigest()
assert actual_hash==attachment.sha256==hashlib.sha256(buffer.getvalue()).hexdigest()
histories=ComplaintHistory.objects.filter(complaint_ref=complaint.complaint_id)
events=NotificationEvent.objects.filter(history__in=histories)
notices=Notification.objects.filter(event__in=events)
graphs={
    'complaint':Complaint.objects.filter(pk=complaint.pk),
    'attachment':Attachment.objects.filter(pk=attachment.pk),
    'receipt':IntakeReceipt.objects.filter(accepted_complaint=complaint),
    'routing':RoutingDecision.objects.filter(complaint_id=complaint.complaint_id),
    'history':histories,'event':events,'notification':notices,
    'email':EmailDelivery.objects.filter(notice__in=notices),
}
values={name:list(q.order_by('pk').values()) for name,q in graphs.items()}
counts={name:len(rows) for name,rows in values.items()}
assert counts['complaint']==counts['attachment']==counts['receipt']==counts['routing']==1
assert counts['history']==counts['event']==2
assert bool(result.replayed)==bool(spec['expect_replay'])
gates={k:getattr(settings,k) for k in ('COMPLAINT_INTAKE_ENABLED','ANONYMOUS_INTAKE_ENABLED',
    'ANONYMOUS_TRACKING_ENABLED','ANONYMOUS_FEEDBACK_ENABLED','ANONYMOUS_PRIVACY_READY')}
assert not any(gates.values())
print('Q05_PERSISTENCE_JSON:'+json.dumps({'replayed':result.replayed,'counts':counts,
    'graph_sha256':hashlib.sha256(json.dumps(values,sort_keys=True,cls=DjangoJSONEncoder).encode()).hexdigest(),
    'evidence_sha256':actual_hash,'file_mode':oct(storage.path(attachment.storage_name) and __import__('os').stat(storage.path(attachment.storage_name)).st_mode & 0o777),
    'release_gates':gates,'evidence_max_bytes':settings.EVIDENCE_MAX_BYTES}))
