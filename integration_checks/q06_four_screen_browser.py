"""Real registration-to-acceptance screen count, not human unaided acceptance."""
import os
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect
from integration_checks.intake_browser import browser_site, chromium, tls_context  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize('width',[1280,320])
def test_first_registration_to_submission_uses_four_visible_pages(chromium, browser_site, width):
    origin,config,_=browser_site
    context=chromium.new_context(ignore_https_errors=True,viewport={'width':width,'height':800},is_mobile=width==320)
    try:
        page=context.new_page();screens=[]
        folder=Path(os.environ.get('SCMS_BROWSER_EVIDENCE_DIR','build/evidence/q06-four-screen'))
        folder.mkdir(parents=True,exist_ok=True)
        def screen():
            screens.append(urlsplit(page.url).path)
            page.screenshot(path=str(folder/f'four-screen-{width}-{len(screens)}.png'),full_page=True)
        page.goto(origin+'/accounts/register/');screen()
        email='q06-'+uuid4().hex+'@example.test'
        page.get_by_label('Full name').fill('Synthetic Four Screen User')
        page.get_by_label('Email',exact=False).fill(email)
        page.get_by_label('Password',exact=False).fill('SyntheticTest123!')
        page.get_by_label('User type').select_option(index=1)
        page.get_by_role('button',name='Register',exact=True).click()
        expect(page.get_by_role('heading',level=1)).to_have_text('Registration received');screen()
        page.locator('main').get_by_label('Email',exact=False).fill(email)
        page.locator('main').get_by_label('Password',exact=False).fill('SyntheticTest123!')
        page.locator('main').get_by_role('button',name='Sign in',exact=True).click()
        expect(page).to_have_url(origin+'/accounts/landing/complainant/');screen()
        page.locator('#id_category').select_option(str(config['category'].pk))
        page.locator('#id_location').select_option(config['location'].code)
        page.locator('#id_priority').select_option('LOW')
        page.get_by_label('Title',exact=False).fill('Synthetic four-page complaint')
        page.get_by_label('Description',exact=False).fill('This synthetic complaint completes the automated four-page workflow.')
        page.get_by_role('button',name='Submit complaint',exact=True).click()
        expect(page.get_by_role('heading',level=1)).to_have_text('Your complaint was submitted');screen()
        assert len(screens)==4
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        (folder/f'four-screen-{width}.txt').write_text('\n'.join(screens)+'\nAutomated path; genuine human acceptance not assessed.\n')
    finally:
        context.close()
