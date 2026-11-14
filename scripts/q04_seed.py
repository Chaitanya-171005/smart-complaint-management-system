"""Q04-only database seed, executed through manage.py shell in an isolated container."""
import json
import sys
import hashlib
from datetime import datetime, timedelta, timezone as dt_timezone
from django.test import Client
from django.utils import timezone
from django.db import transaction
from accounts.models import Department, Location, User
from routing.models import Category, RoutingRule, SLAConfiguration, EscalationPolicy
from complaints.models import Complaint

settings = json.loads(sys.stdin.read())
password = settings['password']
count = settings['complaints']
random_seed = settings.get('seed', 0)

def deterministic_number(index):
    return int.from_bytes(hashlib.sha256(f'{random_seed}:{index}'.encode()).digest()[:8], 'big')
if count < 600 or count > 100000:
    raise ValueError('Use 600 to 100000 complaints; 550 unique action targets are required.')
with transaction.atomic():
    dep, _ = Department.objects.get_or_create(name='Q04 Synthetic Services')
    other, _ = Department.objects.get_or_create(name='Q04 Synthetic Other')
    loc, _ = Location.objects.get_or_create(code='Q04-TEST', defaults={'block':'Q04', 'floor':'1', 'room_area':'Synthetic'})
    cat, _ = Category.objects.get_or_create(name='Q04 Synthetic Category')
    rule, _ = RoutingRule.objects.get_or_create(category=cat, location_code='', defaults={'department':dep})
    if rule.department_id != dep.pk:
        raise ValueError('Synthetic routing rule conflicts with existing data')
    for priority in ('LOW','MEDIUM','HIGH','CRITICAL'):
        SLAConfiguration.objects.get_or_create(category=cat, priority=priority, active=True, defaults={'duration_minutes':1440})
    policy, created = EscalationPolicy.objects.get_or_create(key='default', defaults={'default_department':dep,'interval_minutes':60,'maximum_level':3})
    if not created and policy.default_department_id != dep.pk:
        raise ValueError('Non-Q04 escalation configuration exists; refusing to alter it')
    users = {}
    for role in ('COMPLAINANT','HEAD','STAFF'):
        users[role]=[]
        for i in range(50 if role != 'STAFF' else 2):
            email=f'q04-{role.lower()}-{i+1:03d}@q04.invalid'
            user=User.objects.filter(email=email).first()
            if user:
                if user.role != role or not user.check_password(password) or not user.is_active or (role != 'COMPLAINANT' and user.department_id != dep.pk):
                    raise ValueError('Existing Q04 identity does not match this environment')
            else:
                user=User.objects.create_user(email=email,password=password,full_name=f'Q04 Synthetic {role} {i+1}',role=role,department=dep if role != 'COMPLAINANT' else None)
            users[role].append(user)
    now=datetime(2026, 1, 1, tzinfo=dt_timezone.utc)
    for i in range(count):
        cid=f'SCMS-2099-{i+1:06d}'
        existing=Complaint.objects.filter(complaint_id=cid).first()
        if existing:
            if not existing.title.startswith('Q04 synthetic complaint ') or existing.department_id not in (dep.pk, other.pk) or not existing.submitted_by.email.endswith('@q04.invalid'):
                raise ValueError('Complaint identifier collision; refusing to modify existing record')
            continue
        esc=i>=550 and deterministic_number(i)%5==0
        target_department=dep if i<550 or deterministic_number(i)%4 else other
        Complaint.objects.create(complaint_id=cid,submitted_by=users['COMPLAINANT'][i%50],category_key=str(cat.pk),category=cat.name,location_code=loc.code,block=loc.block,floor=loc.floor,room_area=loc.room_area,title=f'Q04 synthetic complaint {i+1:06d}',description='Synthetic performance test complaint, not a real incident.',priority=('LOW','MEDIUM','HIGH','CRITICAL')[deterministic_number(i)%4],department=target_department,status='ASSIGNED' if i<550 else ('ASSIGNED','IN_PROGRESS','REOPENED')[i%3],submitted_at=now-timedelta(minutes=i),due_at=datetime(2099, 1, 1, tzinfo=dt_timezone.utc),unrouted=False,routing_rule_key=str(rule.pk),is_escalated=esc,escalation_level=int(esc))
actors={'COMPLAINANT':[],'HEAD':[]}
for role in actors:
    for i,u in enumerate(users[role]):
        client=Client(enforce_csrf_checks=True,HTTP_HOST='127.0.0.1')
        client.get('/accounts/login/')
        response=client.post('/accounts/login/',{'email':u.email,'password':password,'csrfmiddlewaretoken':client.cookies['csrftoken'].value})
        if response.status_code != 302 or 'sessionid' not in client.cookies:
            raise ValueError('Synthetic login failed')
        entry={'account_key':f'q04-{role.lower()}-{i+1:03d}','session_cookie':client.cookies['sessionid'].value}
        if role=='HEAD':
            entry['operations']={'action':[{'target_key':f'q04-{i*11+j+1:06d}','path':f'/complaints/SCMS-2099-{i*11+j+1:06d}/assign/','prepare_path':'/routing/queue/','payload':{'assignee':str(users['STAFF'][0].pk),'expected_assignee':'','reason':''}} for j in range(11)]}
        actors[role].append(entry)
print('Q04_JSON:'+json.dumps({'actors':actors,'count':count,'category':cat.pk,'location':loc.code,'reserved_unassigned':Complaint.objects.filter(complaint_id__in=[f'SCMS-2099-{i:06d}' for i in range(1,551)],assignee__isnull=True,status='ASSIGNED').count()}))
