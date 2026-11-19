"""Conservative static color contracts, including later duplicate CSS rules.

These checks test every color declaration for the relevant controls against
all backgrounds used for their states. They are not a browser cascade engine.
"""
import re
from pathlib import Path

import pytest

CSS_PATH = Path(__file__).parent / 'static/ui/scms.css'


def rules(css):
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        declarations = dict(re.findall(r'([\w-]+)\s*:\s*([^;]+)', body))
        yield [s.strip() for s in selectors.split(',')], declarations


def color(value, variables):
    value = value.strip()
    variable = re.search(r'var\((--[\w-]+)\)', value)
    if variable:
        return color(variables[variable.group(1)], variables)
    if value in ('white', 'transparent'):
        return '#ffffff' if value == 'white' else None
    match = re.search(r'#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b', value)
    if not match:
        raise AssertionError(f'Unrecognized color: {value}')
    value = match.group()
    return '#' + ''.join(c * 2 for c in value[1:]) if len(value) == 4 else value


def ratio(a, b):
    def luminance(h):
        channels = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        channels = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(v * w for v, w in zip(channels, (.2126, .7152, .0722)))
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + .05) / (dark + .05)


def palette(css):
    parsed = list(rules(css))
    variables = {}
    for selectors, declarations in parsed:
        if ':root' in selectors:
            variables.update({k: v for k, v in declarations.items() if k.startswith('--')})
    return parsed, variables


def assert_sidebar_contrast(css):
    parsed, variables = palette(css)
    backgrounds, text, labels, outlines = [], [], [], []
    state_selectors = set()
    for selectors, declarations in parsed:
        sidebar_links = [s for s in selectors if s.startswith('.sidebar a')]
        if '.sidebar' in selectors or sidebar_links:
            if 'background' in declarations:
                backgrounds.append(color(declarations['background'], variables))
        if sidebar_links:
            state_selectors.update(sidebar_links)
            if 'color' in declarations:
                text.append(color(declarations['color'], variables))
            if 'outline-color' in declarations:
                outlines.append(color(declarations['outline-color'], variables))
        if '.nav-label' in selectors and 'color' in declarations:
            labels.append(color(declarations['color'], variables))
    assert backgrounds and text and labels and outlines
    assert {'.sidebar a', '.sidebar a:hover', '.sidebar a:active', '.sidebar a:focus-visible', '.sidebar a[aria-current="page"]'} <= state_selectors
    for foreground in text + labels:
        for background in backgrounds:
            assert ratio(foreground, background) >= 4.5, (foreground, background)
    for outline in outlines:
        for background in backgrounds:
            assert ratio(outline, background) >= 3, (outline, background)


def assert_control_contrast(css):
    parsed, variables = palette(css)
    borders, backgrounds = [], [color('var(--bg)', variables)]
    disabled = invalid = False
    for selectors, declarations in parsed:
        controls = [s for s in selectors if s.startswith(('input', 'select', 'textarea')) and '[type=submit]' not in s]
        if not controls:
            continue
        disabled |= any(':disabled' in s for s in controls)
        invalid |= any('[aria-invalid=' in s for s in controls)
        for prop in ('border', 'border-color'):
            if prop in declarations:
                borders.append(color(declarations[prop], variables))
        if 'background' in declarations:
            backgrounds.append(color(declarations['background'], variables))
    assert borders and disabled and invalid
    for border in borders:
        for background in backgrounds:
            assert ratio(border, background) >= 3, (border, background)


def test_sidebar_text_and_focus_contrast_across_all_declared_states():
    assert_sidebar_contrast(CSS_PATH.read_text())


def test_control_boundaries_contrast_across_normal_disabled_and_error_states():
    assert_control_contrast(CSS_PATH.read_text())


@pytest.mark.parametrize('bad_rule', [
    '.sidebar a{color:var(--navy)}',
    '.sidebar a:hover{background:#ffffff}',
    '.nav-label{color:var(--muted)}',
])
def test_sidebar_guard_detects_later_conflicting_overrides(bad_rule):
    with pytest.raises(AssertionError):
        assert_sidebar_contrast(CSS_PATH.read_text() + bad_rule)


def test_boundary_guard_detects_original_low_contrast_border():
    css = CSS_PATH.read_text().replace('#64748b', '#91a2b8')
    with pytest.raises(AssertionError):
        assert_control_contrast(css)
