"""Retired anonymous aliases must never enter F4's full-record detail route."""

import pytest
from django.test import Client
from django.urls import Resolver404, resolve, reverse

from complaints.models import Complaint
from workflow import urls, views
from workflow.models import ComplaintHistory, EmailDelivery, Notification, NotificationEvent

ALIASES = ('anonymous', 'track')
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def production_slash_behavior(settings):
    settings.DEBUG = False
    settings.APPEND_SLASH = True


def client_and_record(user_factory, complaint_factory, authenticated):
    owner = user_factory()
    record = complaint_factory(submitted_by=owner, title='PRIVATE synthetic route-boundary record')
    client = Client(enforce_csrf_checks=True)
    # Obtain a real anti-CSRF cookie from a public form before signing in.
    response = client.get('/accounts/login/')
    assert response.status_code == 200
    token = client.cookies['csrftoken'].value
    if authenticated:
        client.force_login(owner)
    return client, token, record


def snapshot():
    return (
        list(Complaint.objects.order_by('pk').values()),
        *[model.objects.count() for model in
          (ComplaintHistory, NotificationEvent, Notification, EmailDelivery)],
    )


@pytest.mark.parametrize('alias', ALIASES)
def test_alias_resolves_to_explicit_retirement_instead_of_detail(alias):
    match = resolve(f'/complaints/{alias}/')
    assert match.func is urls.retired_anonymous_route
    assert match.func is not views.complaint_detail
    assert match.kwargs == {}


@pytest.mark.parametrize('alias', ALIASES)
@pytest.mark.parametrize('authenticated', [False, True], ids=['anonymous', 'signed-in'])
def test_retired_get_is_404_without_login_redirect_or_private_record(
        alias, authenticated, user_factory, complaint_factory):
    client, _, record = client_and_record(user_factory, complaint_factory, authenticated)
    before = snapshot()
    response = client.get(f'/complaints/{alias}/')
    assert response.status_code == 404
    assert response.resolver_match.func is urls.retired_anonymous_route
    assert 'Location' not in response
    assert record.title.encode() not in response.content
    assert record.complaint_id.encode() not in response.content
    assert snapshot() == before


@pytest.mark.parametrize('alias', ALIASES)
@pytest.mark.parametrize('authenticated', [False, True], ids=['anonymous', 'signed-in'])
@pytest.mark.parametrize('csrf', ['missing', 'incorrect', 'valid', 'untrusted-origin'])
def test_post_preserves_csrf_and_never_enters_detail(
        alias, authenticated, csrf, user_factory, complaint_factory):
    client, token, record = client_and_record(user_factory, complaint_factory, authenticated)
    before = snapshot()
    data = {'complaint_id': record.complaint_id, 'rating': '5'}
    headers = {'HTTP_ORIGIN': 'http://testserver'}
    if csrf != 'missing':
        data['csrfmiddlewaretoken'] = (
            ('A' if token[0] != 'A' else 'B') + token[1:] if csrf == 'incorrect' else token
        )
    if csrf == 'untrusted-origin':
        headers['HTTP_ORIGIN'] = 'https://untrusted.example.test'
    response = client.post(f'/complaints/{alias}/', data, **headers)
    # Middleware rejects unsafe requests before calling the retired view. With
    # valid CSRF the explicit handler still returns 404, never detail's 405/302.
    assert response.status_code == (404 if csrf == 'valid' else 403)
    assert response.resolver_match.func is urls.retired_anonymous_route
    assert 'Location' not in response
    assert record.title.encode() not in response.content
    assert snapshot() == before


@pytest.mark.parametrize('alias', ALIASES)
@pytest.mark.parametrize('authenticated', [False, True], ids=['anonymous', 'signed-in'])
@pytest.mark.parametrize('method', ['get', 'post'])
def test_slashless_alias_only_redirects_to_the_same_retired_handler(
        alias, authenticated, method, user_factory, complaint_factory):
    client, token, _ = client_and_record(user_factory, complaint_factory, authenticated)
    path = f'/complaints/{alias}'
    with pytest.raises(Resolver404):
        resolve(path)
    before = snapshot()
    response = getattr(client, method)(path, {'csrfmiddlewaretoken': token})
    assert response.status_code == 301
    assert response['Location'].split('?', 1)[0] == path + '/'
    canonical = client.get(response['Location'])
    assert canonical.status_code == 404
    assert canonical.resolver_match.func is urls.retired_anonymous_route
    assert snapshot() == before


def test_real_detail_still_works_for_owner_and_denies_other_readers(
        user_factory, complaint_factory):
    owner = user_factory()
    record = complaint_factory(submitted_by=owner)
    path = reverse('workflow:complaint_detail', args=[record.complaint_id])
    assert resolve(path).func is views.complaint_detail
    assert resolve(path).kwargs == {'complaint_id': record.complaint_id}
    client = Client()
    assert client.get(path).status_code == 302
    client.force_login(owner)
    response = client.get(path)
    assert response.status_code == 200
    assert response.context['complaint'].pk == record.pk
    client.force_login(user_factory())
    assert client.get(path).status_code == 404
    anonymous = complaint_factory(anonymous=True)
    assert client.get(reverse('workflow:complaint_detail', args=[anonymous.complaint_id])).status_code == 404


def test_b23_confirmation_route_is_not_shadowed(user_factory, complaint_factory):
    owner = user_factory()
    record = complaint_factory(submitted_by=owner, status='RESOLVED',
                               resolution_remarks='Synthetic repair completed')
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    path = reverse('workflow:confirm', args=[record.complaint_id])
    assert resolve(path).func is views.confirm
    form = client.get(path)
    assert form.status_code == 200
    response = client.post(path, {
        'csrfmiddlewaretoken': client.cookies['csrftoken'].value,
        'revision': form.context['form'].initial['revision'],
        'rating': '5',
    })
    assert response.status_code == 302
    assert response['Location'] == reverse('workflow:complaint_detail', args=[record.complaint_id])
    record.refresh_from_db()
    assert (record.status, record.rating) == ('CLOSED', 5)
    assert client.get(response['Location']).status_code == 200
