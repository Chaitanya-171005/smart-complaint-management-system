"""Built-app assets work with DEBUG=False without publishing private evidence."""
from pathlib import Path
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, override_settings


@pytest.fixture
def roots(tmp_path,settings):
    public=tmp_path/'public';public.mkdir()
    private=tmp_path/'private';private.mkdir()
    for asset in ('scms.css','forms.js'):
        dest=public/'ui'/asset;dest.parent.mkdir(exist_ok=True)
        dest.write_bytes((Path(__file__).parent/'static/ui'/asset).read_bytes())
    (private/'private-evidence.pdf').write_bytes(b'PRIVATE EVIDENCE SENTINEL')
    settings.DEBUG=False
    settings.STATIC_ROOT=public
    settings.PRIVATE_EVIDENCE_ROOT=private
    settings.WHITENOISE_AUTOREFRESH=False
    settings.WHITENOISE_USE_FINDERS=False
    return public,private


@pytest.mark.parametrize('asset,content_type',[('scms.css','text/css'),('forms.js','javascript')])
def test_collected_assets_are_served_without_debug_or_identity(roots,asset,content_type):
    response=Client().get('/static/ui/'+asset,HTTP_COOKIE='sessionid=untrusted-ambient-cookie')
    assert response.status_code==200
    assert content_type in response['Content-Type']
    assert b''.join(response.streaming_content)==(roots[0]/'ui'/asset).read_bytes()
    assert not response.cookies
    assert 'Cookie' not in response.get('Vary','')
    assert Client().head('/static/ui/'+asset).status_code==200


@pytest.mark.parametrize('path',['/static/private-evidence.pdf','/media/private-evidence.pdf','/static/../private/private-evidence.pdf'])
def test_static_delivery_never_maps_the_private_root(roots,path):
    response=Client().get(path)
    assert response.status_code==404
    assert b'PRIVATE EVIDENCE SENTINEL' not in response.content


@pytest.mark.parametrize('relation',['same','private_inside_static','static_inside_private'])
def test_static_and_private_root_overlap_refuses_application_start(roots,settings,relation):
    public,private=roots
    settings.STATIC_ROOT=private if relation in ('same','static_inside_private') else public
    settings.PRIVATE_EVIDENCE_ROOT=(public/'evidence') if relation=='private_inside_static' else private
    if relation=='static_inside_private':settings.STATIC_ROOT=private/'static'
    with pytest.raises(ImproperlyConfigured,match='must be separate'):
        Client().get('/accounts/login/')
