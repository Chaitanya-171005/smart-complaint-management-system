"""Q06's shorter path retains registration privacy, role boundaries and gates."""
import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_generic_receipt_offers_blank_csrf_protected_login(client):
    response = client.get(reverse('accounts:register_done'))
    assert response.status_code == 200
    assert 'no-store' in response['Cache-Control']
    assert b'action="/accounts/login/"' in response.content
    assert b'csrfmiddlewaretoken' in response.content
    assert response.context['form']['email'].value() is None
    assert response.context['form']['password'].value() is None
    protected = Client(enforce_csrf_checks=True)
    assert protected.post(reverse('accounts:login'), {'email':'synthetic@example.test','password':'Synthetic123!'}).status_code == 403


def test_complainant_home_offers_existing_intake_form_only_when_ready(client, complainant_user, routing_configuration, settings):
    client.force_login(complainant_user)
    settings.COMPLAINT_INTAKE_ENABLED = True
    settings.COMPLAINT_EMERGENCY_NOTICE = 'SYNTHETIC Q06 notice, not campus policy.'
    response = client.get(reverse('accounts:landing_complainant'))
    assert response.status_code == 200
    assert b'action="/complaints/new/"' in response.content
    assert response.context['request_token']
    assert response.context['form'].is_bound is False
    assert 'no-store' in response['Cache-Control']
    assert b'SYNTHETIC Q06 notice' in response.content


@pytest.mark.parametrize('enabled,notice', [(False,'Synthetic notice'),(True,''),(True,'   ')])
def test_home_does_not_offer_intake_when_release_prerequisites_are_missing(client, complainant_user, settings, enabled, notice):
    client.force_login(complainant_user)
    settings.COMPLAINT_INTAKE_ENABLED = enabled
    settings.COMPLAINT_EMERGENCY_NOTICE = notice
    response = client.get(reverse('accounts:landing_complainant'))
    assert response.status_code == 200
    assert b'name="request_token"' not in response.content


@pytest.mark.parametrize('role', ['STAFF','HEAD','ADMIN'])
def test_other_role_homes_never_offer_intake_tokens(client, user_factory, department, settings, role):
    settings.COMPLAINT_INTAKE_ENABLED = True
    settings.COMPLAINT_EMERGENCY_NOTICE = 'Synthetic notice'
    client.force_login(user_factory(role=role, department=department if role!='ADMIN' else None))
    response = client.get(reverse('accounts:landing_'+role.lower()))
    assert response.status_code == 200
    assert b'name="request_token"' not in response.content


def test_denied_page_has_safe_guidance_without_changing_permission(client, complainant_user, settings):
    settings.DEBUG = False
    client.force_login(complainant_user)
    response = client.get('/routing/queue/')
    assert response.status_code == 403
    assert b'do not have permission' in response.content
    assert b'Return home' in response.content


@pytest.mark.parametrize('path', ['/anonymous/new/','/anonymous/track/','/anonymous/feedback/'])
def test_private_ui_has_inline_style_without_script_or_asset_requests(client, complainant_user, settings, path):
    settings.DEBUG = False
    client.force_login(complainant_user)
    response = client.get(path)
    assert response.status_code == 503  # Existing release gates remain closed.
    assert b'<style>' in response.content
    assert b'<script' not in response.content
    assert b'<link rel="stylesheet"' not in response.content
    assert 'default-src \'none\'' in response['Content-Security-Policy']
    assert 'script-src \'none\'' in response['Content-Security-Policy']
    assert 'style-src \'unsafe-inline\'' in response['Content-Security-Policy']
    assert complainant_user.full_name.encode() not in response.content
