"""End-to-end user-flow verification through the real HTML pages.

These use Starlette's TestClient (no browser). Playwright smoke tests
live in tests/e2e/ and skip when Chromium cannot launch.
"""
import re

from tests.conftest import csrf_token_from, make_user, page_login


def test_member_core_flow(seeded_app, seeded_client):
    make_user(seeded_app, "alice", "alicepass123")
    client = seeded_client

    home = client.get("/")
    assert home.status_code == 200
    assert "Welcome to your Library" in home.text

    login_page = client.get("/login")
    token = csrf_token_from(login_page.text)
    bad = client.post(
        "/login",
        data={
            "username": "alice",
            "password": "nope-nope",
            "_csrf": token,
            "next": "/account",
        },
    )
    assert bad.status_code == 200
    assert "Invalid username or password." in bad.text

    page_login(client, "alice", "alicepass123")
    account = client.get("/account")
    assert account.status_code == 200
    assert "My account" in account.text
    assert 'href="/admin"' not in account.text

    catalog = client.get("/books")
    assert "Harry Potter" in catalog.text
    detail = client.get("/books/1")
    assert "4 available of 5" in detail.text or "5 available of 5" in detail.text
    token = csrf_token_from(detail.text)
    borrowed = client.post("/books/1/borrow", data={"_csrf": token}, follow_redirects=True)
    assert "Borrowed" in borrowed.text

    account = client.get("/account")
    assert "Harry Potter" in account.text
    return_token = csrf_token_from(account.text)
    match = re.search(r'action="/loans/(\d+)/return"', account.text)
    assert match
    returned = client.post(
        f"/loans/{match.group(1)}/return",
        data={"_csrf": return_token, "next": "/account"},
        follow_redirects=True,
    )
    assert "Returned" in returned.text

    calendar = client.get("/calendar")
    assert calendar.status_code == 200
    assert "Add event" in calendar.text or "calendar" in calendar.text.lower()

    logout_token = csrf_token_from(client.get("/").text)
    logged_out = client.post("/logout", data={"_csrf": logout_token}, follow_redirects=True)
    assert "logged out" in logged_out.text.lower()
    assert client.get("/account", follow_redirects=False).status_code == 303


def test_admin_flow_and_404(client, admin_account):
    page_login(client, **admin_account)
    admin = client.get("/admin")
    assert admin.status_code == 200
    assert "Available books" in admin.text
    assert "Recent activity" in admin.text
    assert client.get("/books/new").status_code == 200
    assert client.get("/definitely-not-a-page").status_code == 404
