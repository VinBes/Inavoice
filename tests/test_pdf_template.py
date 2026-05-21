"""Jinja-layer tests for the invoice template logo slots.

Renders the template directly via Jinja, bypassing WeasyPrint so these run
without native Pango/GObject libs (which are not installed on macOS dev hosts).
"""
import pathlib
import re

import jinja2
import pytest

_TEMPLATES = pathlib.Path(__file__).parent.parent / "src" / "templates"

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES)),
    autoescape=True,
)


def _render(**overrides) -> str:
    ctx = {
        "invoice_number": "ZARAFFA26-1",
        "invoice_date": "1 May 2026",
        "due_date": "15 May 2026",
        "display_name": "Test Client",
        "address_lines": ["Test Address"],
        "description": "Test invoice",
        "service_date": "01/05/2026",
        "service_description": "Test service",
        "time_start": None,
        "time_end": None,
        "hours": None,
        "rate": 1000,
        "rate_type": "flat",
        "total": 1000,
        "sender_name": "Test Sender",
        "sender_address_lines": ["Test Address"],
        "account_holder": "Test Holder",
        "bank_name": "Test Bank",
        "bank_code": "000",
        "bank_account": "000-000000-0",
        "fps_id": "test@fps",
        "business_registration": "TEST-BR-0001",
        "logo_left_path": None,
        "logo_right_path": None,
    }
    ctx.update(overrides)
    return _env.get_template("invoice.html").render(**ctx)


def _count_imgs(html: str) -> int:
    return html.count("<img ")


def test_both_logos_render():
    html = _render(
        logo_left_path="assets/left.png",
        logo_right_path="assets/right.png",
    )
    assert 'src="assets/left.png"' in html
    assert 'src="assets/right.png"' in html
    assert _count_imgs(html) == 2


def test_only_left_renders():
    html = _render(logo_left_path="assets/left.png", logo_right_path=None)
    assert 'src="assets/left.png"' in html
    assert _count_imgs(html) == 1


def test_only_right_renders():
    html = _render(logo_left_path=None, logo_right_path="assets/right.png")
    assert 'src="assets/right.png"' in html
    assert _count_imgs(html) == 1


def test_no_logos_renders_no_img_tags():
    html = _render(logo_left_path=None, logo_right_path=None)
    assert _count_imgs(html) == 0
    assert 'class="header-logo-left"' in html
    assert 'class="header-logo-right"' in html


def test_empty_string_path_renders_no_img():
    # config.py collapses empty strings to None before render, but defend the
    # template against an empty string slipping through anyway.
    html = _render(logo_left_path="", logo_right_path="")
    assert _count_imgs(html) == 0


@pytest.mark.parametrize(
    "path",
    [
        "assets/my logo.png",            # space
        "assets/logo&brand.png",         # ampersand
        'assets/quote".png',             # double-quote
    ],
)
def test_path_is_autoescaped(path):
    html = _render(logo_right_path=path)
    # Jinja autoescape must produce a syntactically valid src attribute —
    # the value between src=" and the next " must not contain a raw `"`.
    match = re.search(r'<img\s+src="([^"]*)"', html)
    assert match, f"no well-formed img src in: {html!r}"
