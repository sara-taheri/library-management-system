"""Unit tests for the authentication service (no HTTP layer involved)."""
import pytest
from sqlalchemy import select

from app.models import User
from app.services.auth_service import AuthError, authenticate, register_user
from app.utils.security import BCRYPT, LEGACY_SHA256, verify_password
from tests.conftest import make_user


def test_register_creates_bcrypt_user(db_session):
    user = register_user(db_session, username="alice", password="wonderland1")
    assert user.id is not None
    assert user.role == "member"
    assert user.hash_algorithm == BCRYPT
    assert user.password_hash.startswith("$2b$")
    assert verify_password("wonderland1", user.password_hash, BCRYPT)


def test_register_rejects_duplicate_username_case_insensitive(app, db_session):
    make_user(app, "BobReader", "password123")
    with pytest.raises(AuthError) as exc_info:
        register_user(db_session, username="bobreader", password="password123")
    assert exc_info.value.status_code == 409


def test_register_rejects_duplicate_email(app, db_session):
    make_user(app, "carol", "password123", email="carol@example.com")
    with pytest.raises(AuthError) as exc_info:
        register_user(
            db_session, username="carol2", password="password123", email="carol@example.com"
        )
    assert exc_info.value.status_code == 409


def test_register_validates_username_format(db_session):
    with pytest.raises(AuthError):
        register_user(db_session, username="in valid!", password="password123")
    with pytest.raises(AuthError):
        register_user(db_session, username="ab", password="password123")


def test_register_validates_password_length(db_session):
    with pytest.raises(AuthError):
        register_user(db_session, username="dave", password="short")


def test_register_never_accepts_unknown_role(db_session):
    user = register_user(db_session, username="erin", password="password123", role="wizard")
    assert user.role == "member"


def test_authenticate_wrong_password_returns_none(app, db_session):
    make_user(app, "frank", "password123")
    assert authenticate(db_session, username="frank", password="wrongpass1") is None


def test_authenticate_unknown_user_returns_none(db_session):
    assert authenticate(db_session, username="nobody", password="whatever1") is None


def test_authenticate_upgrades_legacy_hash(app, db_session):
    make_user(app, "gina", "legacypass1", legacy=True)

    user = authenticate(db_session, username="gina", password="legacypass1")
    assert user is not None

    stored = db_session.scalar(select(User).where(User.username == "gina"))
    assert stored.hash_algorithm == BCRYPT
    assert stored.password_hash.startswith("$2b$")
    assert verify_password("legacypass1", stored.password_hash, BCRYPT)
    # The old hash is really gone.
    assert stored.password_hash != LEGACY_SHA256
