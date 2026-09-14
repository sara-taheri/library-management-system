"""Shared pytest fixtures and helpers.

Every test gets an isolated application instance backed by a throwaway
SQLite file in pytest's tmp_path - tests never touch `data/library.db`
or the legacy JSON files.
"""
import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Book, User
from app.utils.security import LEGACY_SHA256, hash_password


@pytest.fixture()
def app(tmp_path):
    db_file = tmp_path / "test_library.db"
    application = create_app(database_url=f"sqlite:///{db_file}")
    yield application
    application.state.engine.dispose()


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def seeded_app(app):
    """App pre-loaded with a small catalog (mirrors the legacy books.json)."""
    session_factory = app.state.session_factory
    with session_factory() as db:
        db.add_all(
            [
                Book(
                    id=1,
                    title="Harry Potter",
                    author="J.K. Rowling",
                    genre="Fantasy",
                    total_copies=5,
                    available_copies=4,
                ),
                Book(
                    id=2,
                    title="The Notebook",
                    author="Nicholas Sparks",
                    genre="Romance",
                    total_copies=4,
                    available_copies=4,
                ),
                Book(
                    id=3,
                    title="Hamlet",
                    author="William Shakespeare",
                    genre="Drama",
                    total_copies=7,
                    available_copies=7,
                ),
            ]
        )
        db.commit()
    return app


@pytest.fixture()
def seeded_client(seeded_app):
    with TestClient(seeded_app) as test_client:
        yield test_client


@pytest.fixture()
def db_session(app):
    """A raw database session bound to the test application."""
    with app.state.session_factory() as db:
        yield db


# ------------------------------------------------------------- user helpers


def make_user(
    app,
    username: str,
    password: str,
    role: str = "member",
    legacy: bool = False,
    email: str | None = None,
) -> None:
    """Insert a user directly into the test database.

    legacy=True stores an unsalted SHA-256 hash flagged
    hash_algorithm="legacy_sha256" - exactly what the JSON migration
    produces - so tests can exercise the transparent bcrypt upgrade.
    """
    if legacy:
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        algorithm = LEGACY_SHA256
    else:
        password_hash = hash_password(password)
        algorithm = "bcrypt"
    with app.state.session_factory() as db:
        db.add(
            User(
                username=username,
                email=email,
                password_hash=password_hash,
                hash_algorithm=algorithm,
                role=role,
            )
        )
        db.commit()


@pytest.fixture()
def member_account(app):
    make_user(app, "testmember", "password123")
    return {"username": "testmember", "password": "password123"}


@pytest.fixture()
def admin_account(app):
    make_user(app, "testadmin", "adminpass123", role="admin")
    return {"username": "testadmin", "password": "adminpass123"}


@pytest.fixture()
def legacy_account(app):
    """An account with a legacy SHA-256 hash (like migrated users.json rows)."""
    make_user(app, "legacyuser", "legacypass123", legacy=True)
    return {"username": "legacyuser", "password": "legacypass123"}


def api_login(client: TestClient, username: str, password: str):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


def csrf_token_from(html: str) -> str:
    """Extract the first CSRF token embedded in a rendered page."""
    match = re.search(r'name="_csrf"\s+value="([^"]+)"', html)
    assert match, "CSRF token not found in page"
    return match.group(1)


def page_login(
    client: TestClient,
    username: str,
    password: str,
    next_url: str = "/account",
    follow: bool = True,
):
    """Drive the real HTML login form (GET token, then POST), like a browser."""
    get_response = client.get("/login")
    token = csrf_token_from(get_response.text)
    return client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "_csrf": token,
            "next": next_url,
        },
        follow_redirects=follow,
    )
