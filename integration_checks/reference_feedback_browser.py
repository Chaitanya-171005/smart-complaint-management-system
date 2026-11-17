"""Native Chromium submissions at desktop/320px; synthetic TLS and Redis fixture.

The Redis fixture executes the actual Lua body with emulated configuration;
these browser checks do not establish deployed Redis/ingress acceptance.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path

import pytest
from django.db import close_old_connections
from django.utils import timezone
from playwright.sync_api import expect

from complaints.models import Complaint
from complaints.references import hash_reference
from complaints.test_tracking import backend  # noqa: F401
from integration_checks.intake_browser import browser_site as intake_site, chromium, tls_context  # noqa: F401
from workflow.models import AnonymousResolutionFeedback

pytestmark = pytest.mark.django_db(transaction=True)
REFERENCE = 'c' * 32


@pytest.fixture
def browser_site(intake_site, backend, settings, complaint_factory, user_factory, request):
    # Complete ORM setup before the dependent Chromium fixture starts its loop.
    settings.SCMS_HTTPS_MODE = 'proxy'
    settings.SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    settings.ANONYMOUS_TRACKING_TRUSTED_PROXY_CIDRS = ['127.0.0.1/32', '::1/128']
    settings.ANONYMOUS_FEEDBACK_ENABLED = True
    settings.COMPLAINT_MAX_REOPENS = 2
    decision = request.node.callspec.params['decision']
    complaint = complaint_factory(anonymous=True, reference_digest=hash_reference(REFERENCE),
        status='RESOLVED', resolved_at=timezone.now(), reopen_count=2 if decision == 'limit' else 0,
        resolution_remarks='PRIVATE synthetic resolver remarks')
    user_factory(role='HEAD', department=complaint.department)
    return intake_site[0], complaint.pk


def persisted(pk):
    def read():
        close_old_connections()
        try:
            record = Complaint.objects.get(pk=pk)
            return record.status, record.rating, AnonymousResolutionFeedback.objects.filter(complaint=record).count()
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(read).result()


@pytest.mark.parametrize('width', [320, 1280])
@pytest.mark.parametrize('decision', ['confirm', 'reject', 'limit'])
def test_native_reference_feedback_is_private_accessible_and_persisted(chromium, browser_site, width, decision):
    origin, pk = browser_site
    context = chromium.new_context(ignore_https_errors=True, viewport={'width':width,'height':740})
    try:
        page = context.new_page()
        response = page.goto(origin+'/anonymous/feedback/')
        assert response.status == 200
        page.get_by_label('Private reference', exact=True).fill(REFERENCE)
        with page.expect_response(lambda r:r.request.method == 'POST' and '/anonymous/feedback/' in r.url) as sent:
            page.get_by_role('button', name='Check status for feedback', exact=True).click()
        assert sent.value.status == 200
        assert REFERENCE not in page.content()
        assert 'PRIVATE synthetic resolver remarks' not in page.content()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.get_by_label('Private reference', exact=True).fill(REFERENCE)
        if decision == 'confirm':
            page.get_by_label('Optional confirmation rating (1–5)').fill('5')
            button = 'Confirm resolution and close'
            expected, rating = 'CLOSED', 5
        else:
            page.get_by_label('Rejection reason', exact=True).fill('The synthetic repair remains incomplete in this room.')
            button = 'Reject resolution and request further work'
            expected, rating = ('REOPENED' if decision == 'reject' else 'RESOLVED'), None
        with page.expect_response(lambda r:r.request.method == 'POST' and '/anonymous/feedback/' in r.url) as sent:
            page.get_by_role('button', name=button, exact=True).click()
        assert sent.value.status == 200
        expect(page.get_by_role('status')).to_be_visible()
        assert REFERENCE not in page.content()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert persisted(pk) == (expected, rating, 1)
        page.goto(origin+'/anonymous/track/')
        page.get_by_label('Private tracking reference').fill(REFERENCE)
        with page.expect_response(lambda r:r.request.method == 'POST' and '/anonymous/track/' in r.url) as tracked:
            page.get_by_role('button', name='Check status', exact=True).click()
        assert tracked.value.status == 200
        assert REFERENCE not in page.content()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        folder = os.environ.get('SCMS_BROWSER_EVIDENCE_DIR')
        if folder:
            page.screenshot(path=str(Path(folder)/f'feedback-tracking-{decision}-{width}.png'), full_page=True)
    finally:
        context.close()
