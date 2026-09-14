"""Tests for the server-rendered pages: forms, CSRF, flashes, redirects, guards.

These drive the real HTML forms exactly like a browser would - the same
flows the future Playwright end-to-end tests will cover.
"""
from urllib.parse import quote

from sqlalchemy import select

from app.models import User
from app.utils.security import BCRYPT
from tests.conftest import api_login, csrf_token_from, make_user, page_login


# ------------------------------------------------------------------- home


def test_home_is_public_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Welcome to your Library" in response.text


# ------------------------------------------------------------------ login


def test_login_page_renders_form_with_csrf(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert 'name="_csrf"' in response.text
    assert csrf_token_from(response.text)


def test_page_login_success_lands_on_account(client, member_account):
    response = page_login(client, **member_account)
    assert response.status_code == 200
    assert response.url.path == "/account"
    assert member_account["username"] in response.text
    assert "Welcome back" in response.text  # success flash rendered


def test_page_login_invalid_credentials_rerenders_with_error(client, member_account):
    login_page = client.get("/login")
    token = csrf_token_from(login_page.text)
    response = client.post(
        "/login",
        data={
            "username": member_account["username"],
            "password": "wrong-password",
            "_csrf": token,
            "next": "/account",
        },
    )
    assert response.status_code == 200
    assert "Invalid username or password." in response.text
    # The typed username is preserved in the form.
    assert f'value="{member_account["username"]}"' in response.text


def test_page_login_requires_csrf_token(client, member_account):
    response = client.post(
        "/login",
        data={"username": member_account["username"], "password": member_account["password"]},
        follow_redirects=True,
    )
    assert response.url.path == "/login"
    assert "session expired" in response.text.lower()
    # And the user is NOT logged in.
    assert client.get("/api/auth/me").status_code == 401


def test_page_login_blocks_open_redirect(client, member_account):
    response = page_login(
        client, **member_account, next_url="https://evil.example/phish"
    )
    assert response.url.path == "/account"  # fell back to the safe default


def test_page_login_honours_safe_next(client, member_account):
    response = page_login(client, **member_account, next_url="/")
    assert response.url.path == "/"


def test_login_page_redirects_authenticated_user(client, member_account):
    api_login(client, **member_account)
    response = client.get("/login", follow_redirects=True)
    assert response.url.path == "/account"


# --------------------------------------------------------------- register


def test_page_register_flow_creates_account_and_auto_logs_in(client):
    register_page = client.get("/register")
    token = csrf_token_from(register_page.text)
    response = client.post(
        "/register",
        data={
            "username": "pagereader",
            "email": "page@example.com",
            "password": "reading123",
            "confirm_password": "reading123",
            "_csrf": token,
        },
        follow_redirects=True,
    )
    assert response.url.path == "/account"
    assert "pagereader" in response.text
    # The session really works (API agrees).
    assert client.get("/api/auth/me").json()["username"] == "pagereader"


def test_page_register_password_mismatch(client):
    token = csrf_token_from(client.get("/register").text)
    response = client.post(
        "/register",
        data={
            "username": "mismatch",
            "email": "",
            "password": "reading123",
            "confirm_password": "different123",
            "_csrf": token,
        },
    )
    assert response.status_code == 200
    assert "Passwords do not match." in response.text


def test_page_register_duplicate_username_shows_error(client, member_account):
    token = csrf_token_from(client.get("/register").text)
    response = client.post(
        "/register",
        data={
            "username": member_account["username"],
            "email": "",
            "password": "reading123",
            "confirm_password": "reading123",
            "_csrf": token,
        },
    )
    assert response.status_code == 200
    assert "already taken" in response.text


def test_page_register_requires_csrf(client):
    response = client.post(
        "/register",
        data={
            "username": "nocsrf",
            "password": "reading123",
            "confirm_password": "reading123",
        },
        follow_redirects=True,
    )
    assert response.url.path == "/register"
    assert "session expired" in response.text.lower()


# ----------------------------------------------------------------- logout


def test_page_logout_via_form(client, member_account):
    page_login(client, **member_account)

    account_page = client.get("/account")
    token = csrf_token_from(account_page.text)
    response = client.post("/logout", data={"_csrf": token}, follow_redirects=True)

    assert response.url.path == "/"
    assert "logged out" in response.text.lower()
    # Session is gone.
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/account", follow_redirects=False).status_code == 303


# ------------------------------------------------------------- protected


def test_account_requires_login(client):
    response = client.get("/account", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/login?next={quote('/account')}"


def test_admin_page_denied_for_member(client, member_account):
    page_login(client, **member_account)
    response = client.get("/admin", follow_redirects=True)
    assert response.url.path == "/account"
    assert "Access denied. Admins only." in response.text


def test_admin_page_ok_for_admin(client, admin_account):
    page_login(client, **admin_account)
    response = client.get("/admin")
    assert response.status_code == 200
    assert "Admin overview" in response.text
    assert "Members" in response.text


def test_admin_page_requires_login(client):
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/login?next={quote('/admin')}"


# --------------------------------------------- legacy accounts via the UI


def test_legacy_account_can_log_in_through_pages(app, client, legacy_account):
    response = page_login(client, **legacy_account)
    assert response.url.path == "/account"

    with app.state.session_factory() as db:
        stored = db.scalar(select(User).where(User.username == legacy_account["username"]))
        assert stored.hash_algorithm == BCRYPT  # upgraded transparently


# ------------------------------------------------------------ error pages


def test_unknown_page_renders_html_404(client):
    response = client.get("/definitely-not-a-page")
    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "Page not found" in response.text


def test_api_404_stays_json(client):
    response = client.get("/api/books/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Book not found"}
