"""Tests for the JSON authentication API and RBAC-protected admin API."""
from sqlalchemy import select

from app.models import User
from app.utils.security import BCRYPT, verify_password
from tests.conftest import api_login, make_user

INVALID_DETAIL = "Invalid username or password."


# ------------------------------------------------------------ registration


def test_register_success(client):
    response = client.post(
        "/api/auth/register",
        json={"username": "newreader", "password": "reading123", "email": "r@example.com"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["username"] == "newreader"
    assert body["user"]["role"] == "member"
    assert "password" not in body["user"]  # hash must never leak
    assert "password_hash" not in body["user"]


def test_register_duplicate_username_conflict(client, member_account):
    response = client.post(
        "/api/auth/register",
        json={"username": "TestMember", "password": "reading123"},  # case differs
    )
    assert response.status_code == 409
    assert "already taken" in response.json()["detail"]


def test_register_duplicate_email_conflict(app, client):
    make_user(app, "someone", "password123", email="dupe@example.com")
    response = client.post(
        "/api/auth/register",
        json={"username": "someoneelse", "password": "reading123", "email": "dupe@example.com"},
    )
    assert response.status_code == 409


def test_register_weak_password_rejected(client):
    response = client.post(
        "/api/auth/register", json={"username": "weakling", "password": "short"}
    )
    assert response.status_code == 422


def test_register_invalid_username_rejected(client):
    response = client.post(
        "/api/auth/register", json={"username": "has spaces!", "password": "reading123"}
    )
    assert response.status_code == 422


def test_register_invalid_email_rejected(client):
    response = client.post(
        "/api/auth/register",
        json={"username": "bademail", "password": "reading123", "email": "not-an-email"},
    )
    assert response.status_code == 422


def test_register_cannot_self_assign_admin(client):
    response = client.post(
        "/api/auth/register",
        json={"username": "hacker", "password": "reading123", "role": "admin"},
    )
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "member"  # extra field ignored


# ----------------------------------------------------------------- login


def test_login_success_starts_session(client, member_account):
    response = api_login(client, **member_account)
    assert response.status_code == 200
    assert response.json()["user"]["username"] == member_account["username"]

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == member_account["username"]


def test_login_wrong_password_401_generic_message(client, member_account):
    response = api_login(client, member_account["username"], "totally-wrong")
    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_DETAIL
    assert client.get("/api/auth/me").status_code == 401


def test_login_unknown_user_401_same_message(client):
    """Identical error for unknown user vs wrong password (no enumeration)."""
    response = api_login(client, "ghostuser", "whatever123")
    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_DETAIL


def test_login_legacy_account_upgrades_hash_to_bcrypt(app, client, legacy_account):
    response = api_login(client, **legacy_account)
    assert response.status_code == 200

    with app.state.session_factory() as db:
        stored = db.scalar(select(User).where(User.username == legacy_account["username"]))
        assert stored.hash_algorithm == BCRYPT
        assert verify_password(legacy_account["password"], stored.password_hash, BCRYPT)

    # Second login goes through the bcrypt path.
    client.post("/api/auth/logout")
    assert api_login(client, **legacy_account).status_code == 200


def test_logout_ends_session(client, member_account):
    assert api_login(client, **member_account).status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_me_unauthenticated(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


# ------------------------------------------------- RBAC / admin endpoints


def test_admin_overview_unauthenticated(client):
    assert client.get("/api/admin/overview").status_code == 401


def test_admin_overview_forbidden_for_member(client, member_account):
    api_login(client, **member_account)
    response = client.get("/api/admin/overview")
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


def test_admin_overview_ok_for_admin(client, admin_account):
    api_login(client, **admin_account)
    response = client.get("/api/admin/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["users"] == 1
    assert {"books", "loans_total", "loans_active", "events"} <= set(body)
