"""Shared UI contracts: real navigation, role separation and protected forms."""
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.test import Client
from django.urls import resolve, reverse

pytestmark = pytest.mark.django_db


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.hrefs.extend(value for key, value in attrs if key == 'href')


@pytest.mark.parametrize('role,expected,absent', [
    ('COMPLAINANT', ['complaints:submit', 'workflow:complaint_list', 'workflow:dashboard'], ['routing:queue', 'accounts:admin_users']),
    ('STAFF', ['routing:queue'], ['complaints:submit', 'accounts:admin_users', 'workflow:dashboard']),
    ('HEAD', ['routing:queue', 'workflow:dashboard'], ['complaints:submit', 'accounts:admin_users']),
    ('ADMIN', ['accounts:admin_users', 'accounts:admin_departments', 'accounts:admin_locations', 'routing:configuration', 'accounts:admin_audit'], ['routing:queue', 'complaints:submit', 'workflow:dashboard']),
])
def test_role_landing_navigation(client, user_factory, department, role, expected, absent):
    user = user_factory(role=role, department=department if role in ('HEAD', 'STAFF') else None)
    client.force_login(user)
    response = client.get(reverse('accounts:landing_' + role.lower()))
    assert response.status_code == 200
    html = response.content.decode()
    assert 'ui/scms.css' in html and 'name="viewport"' in html
    assert 'csrfmiddlewaretoken' in html and 'Skip to content' in html
    assert 'will appear here' not in html
    links = Links()
    links.feed(html)
    for name in expected + ['workflow:notifications']:
        assert reverse(name) in links.hrefs
    for name in absent:
        assert reverse(name) not in links.hrefs
    for href in links.hrefs:
        if href.startswith('/'):
            resolve(href)
    for name in expected:
        assert client.get(reverse(name)).status_code in (200, 503)


@pytest.mark.parametrize('name', ['accounts:login', 'accounts:register', 'accounts:register_done', 'complaints:anonymous_submit', 'complaints:track_reference'])
def test_public_shell(client, name):
    response = client.get(reverse(name))
    assert response.status_code in (200, 503)
    html = response.content.decode()
    assert 'ui/scms.css' in html and 'id="main"' in html
    assert 'Workspace' not in html


def test_all_templates_compile_and_stylesheet_is_discoverable():
    root = Path(__file__).resolve().parents[1]
    for app in ('accounts', 'complaints', 'routing', 'workflow'):
        for path in (root / app / 'templates' / app).glob('*.html'):
            get_template(f'{app}/{path.name}')
    assert finders.find('ui/scms.css')
    assert finders.find('ui/forms.js')


def test_logout_and_login_keep_csrf_protection(user_factory):
    client = Client(enforce_csrf_checks=True)
    assert client.post(reverse('accounts:login'), {'email': 'test@example.test', 'password': 'example'}).status_code == 403
    client.force_login(user_factory())
    response = client.get(reverse('accounts:landing_complainant'))
    assert b'csrfmiddlewaretoken' in response.content
    assert client.post(reverse('accounts:logout')).status_code == 403
    assert client.get(reverse('accounts:logout')).status_code == 405


@pytest.mark.parametrize('role', ['COMPLAINANT', 'STAFF', 'HEAD'])
def test_admin_navigation_is_backed_by_access_restrictions(client, user_factory, department, role):
    client.force_login(user_factory(role=role, department=department))
    for name in ('accounts:admin_users', 'routing:configuration', 'accounts:admin_audit'):
        assert client.get(reverse(name)).status_code in (302, 403, 404)


def test_queue_links_only_offer_staff_their_own_work(client, staff_user, department, user_factory, complaint_factory):
    mine = complaint_factory(department=department, assignee=staff_user)
    other = complaint_factory(department=department, assignee=user_factory(role='STAFF', department=department))
    client.force_login(staff_user)
    html = client.get(reverse('routing:queue')).content.decode()
    assert reverse('workflow:work_status', args=[mine.complaint_id]) in html
    assert reverse('workflow:work_status', args=[other.complaint_id]) not in html


@pytest.mark.parametrize('asset', ['ui/scms.css', 'ui/forms.js'])
def test_local_static_assets_can_be_served(rf, asset):
    from django.contrib.staticfiles.views import serve
    response = serve(rf.get('/static/' + asset), asset, insecure=True)
    assert response.status_code == 200
    assert b''.join(response.streaming_content)
    response.close()
