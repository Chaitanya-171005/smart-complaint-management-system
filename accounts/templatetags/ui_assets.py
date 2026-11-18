"""Inline the fixed repository stylesheet on private, script-free surfaces."""
from functools import lru_cache
from pathlib import Path

from django import template
from django.utils.safestring import mark_safe

register = template.Library()
CSS_PATH = Path(__file__).resolve().parents[1] / 'static/ui/scms.css'


@register.simple_tag
@lru_cache(maxsize=1)
def private_ui_css():
    # No path or content is supplied by a request, user, upload or settings.
    # Keeping CSS inline avoids an automatic asset request with ambient cookies.
    css = CSS_PATH.read_text(encoding='utf-8')
    if '</style' in css.lower():
        raise ValueError('Repository stylesheet contains an HTML closing tag.')
    return mark_safe(css)  # nosec B308 - fixed reviewed repository CSS, no user content
