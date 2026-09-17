"""Lightweight Playwright smoke tests for the main student-demo flows.

Each test starts from a fresh browser context (no shared cookies).
Selectors use roles and labels from the real pages, not brittle CSS.

These tests skip when Playwright is missing or Chromium cannot launch.
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, expect

from tests.e2e.conftest import ADMIN, MEMBER


def _login(page: Page, username: str, password: str) -> None:
    page.goto("/login")
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Log in").click()


def test_homepage_loads(browser_page: Page):
    page = browser_page
    page.goto("/")
    expect(page.get_by_role("heading", name="Welcome to your Library")).to_be_visible()
    expect(page.get_by_role("navigation", name="Main navigation")).to_be_visible()
    expect(page.get_by_role("link", name="Catalog")).to_be_visible()


def test_login_success_opens_account(browser_page: Page):
    page = browser_page
    _login(page, MEMBER["username"], MEMBER["password"])
    expect(page).to_have_url("**/account")
    expect(page.get_by_role("heading", name="My account")).to_be_visible()
    expect(page.get_by_text(MEMBER["username"])).to_be_visible()


def test_login_invalid_credentials_show_error(browser_page: Page):
    page = browser_page
    _login(page, MEMBER["username"], "wrong-password")
    expect(page.get_by_role("alert")).to_contain_text("Invalid username or password.")
    expect(page).to_have_url("**/login")


def test_catalog_page_lists_seeded_books(browser_page: Page):
    page = browser_page
    page.goto("/books")
    expect(page.get_by_role("heading", name="Book catalog")).to_be_visible()
    expect(page.get_by_role("link", name="Harry Potter")).to_be_visible()
    expect(page.get_by_text("3 books found")).to_be_visible()


def test_member_is_denied_admin_dashboard(browser_page: Page):
    page = browser_page
    _login(page, MEMBER["username"], MEMBER["password"])
    page.goto("/admin")
    expect(page).to_have_url("**/account")
    expect(page.get_by_text("Access denied. Admins only.")).to_be_visible()
    expect(page.get_by_role("link", name="Admin")).to_have_count(0)


def test_admin_dashboard_shows_library_metrics(browser_page: Page):
    page = browser_page
    _login(page, ADMIN["username"], ADMIN["password"])
    page.goto("/admin")
    expect(page.get_by_role("heading", name="Admin overview")).to_be_visible()
    expect(page.get_by_text("Available books")).to_be_visible()
    expect(page.get_by_text("Overdue loans")).to_be_visible()
    expect(page.get_by_text("Recent activity")).to_be_visible()


def test_borrow_and_return_book(browser_page: Page):
    page = browser_page
    _login(page, MEMBER["username"], MEMBER["password"])
    page.goto("/books/1")
    page.get_by_role("button", name="Borrow this book").click()
    expect(page.get_by_text("Borrowed 'Harry Potter'")).to_be_visible()
    page.get_by_role("button", name="Return book").click()
    expect(page.get_by_text("Returned 'Harry Potter'")).to_be_visible()


def test_create_calendar_event(browser_page: Page):
    page = browser_page
    _login(page, MEMBER["username"], MEMBER["password"])
    page.goto("/calendar/new?date=2026-09-22")
    page.get_by_label("Title").fill("Study group")
    page.get_by_role("button", name="Create event").click()
    expect(page.get_by_text("Study group")).to_be_visible()
    expect(page.get_by_text("Event 'Study group' was created.")).to_be_visible()
