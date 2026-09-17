"""Focused markup tests for the M2 design-system / accessibility pass.

These check stable landmarks and navigation state - not visual snapshots.
"""
from pathlib import Path
from types import SimpleNamespace

from app.web import nav_active
from tests.conftest import page_login

CSS_PATH = Path(__file__).resolve().parent.parent / "app" / "static" / "app.css"


def test_skip_link_and_main_landmark(client):
    html = client.get("/").text
    assert 'href="#main-content"' in html
    assert "Skip to content" in html
    assert 'id="main-content"' in html
    assert "<main" in html
    assert 'aria-label="Main navigation"' in html


def test_catalog_api_lives_in_footer_not_primary_nav(client):
    html = client.get("/").text
    before_footer, footer = html.split("<footer", 1)
    assert 'href="/api/books"' not in before_footer
    assert 'href="/api/books"' in footer
    assert "Catalog API" in footer


def test_aria_current_marks_active_section(client):
    home = client.get("/").text
    assert 'href="/" aria-current="page"' in home
    assert 'href="/books" aria-current="page"' not in home

    catalog = client.get("/books").text
    assert 'href="/books" aria-current="page"' in catalog
    assert 'href="/" aria-current="page"' not in catalog

    calendar = client.get("/calendar").text
    assert 'href="/calendar" aria-current="page"' in calendar


def test_aria_current_follows_nested_catalog_pages(seeded_client):
    detail = seeded_client.get("/books/1").text
    assert 'href="/books" aria-current="page"' in detail


def test_dashboard_nav_current_when_signed_in(client, member_account):
    page_login(client, **member_account)
    account = client.get("/account").text
    assert 'href="/account" aria-current="page"' in account
    assert 'href="/admin"' not in account  # members do not see Admin


def test_login_fields_have_labels(client):
    html = client.get("/login").text
    assert '<label for="username">' in html
    assert 'id="username"' in html
    assert '<label for="password">' in html
    assert 'id="password"' in html


def test_catalog_table_has_column_headers(seeded_client):
    html = seeded_client.get("/books").text
    assert 'scope="col">Title</th>' in html
    assert 'scope="col">Author</th>' in html


def test_css_defines_focus_visible_and_breakpoints():
    css = CSS_PATH.read_text(encoding="utf-8")
    assert ":focus-visible" in css
    assert ".skip-link" in css
    assert "@media (max-width: 768px)" in css
    assert "@media (max-width: 480px)" in css
    assert ".table-wrap" in css
    assert "overflow-x: auto" in css


def test_nav_active_helper():
    def req(path):
        return SimpleNamespace(url=SimpleNamespace(path=path))

    assert nav_active(req("/"), "/") is True
    assert nav_active(req("/books"), "/") is False
    assert nav_active(req("/books"), "/books") is True
    assert nav_active(req("/books/1"), "/books") is True
    assert nav_active(req("/admin/loans"), "/admin") is True
    assert nav_active(req("/account"), "/admin") is False
