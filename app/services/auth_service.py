"""Authentication & account business logic.

Single source of truth for registration/login rules - used by both the
JSON API and the server-rendered pages (and reusable from scripts or
background tasks since it only needs a database session).
"""
import logging
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User
from app.models.user import ROLE_ADMIN, ROLE_MEMBER
from app.utils.security import (
    BCRYPT,
    LEGACY_SHA256,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    equalise_timing,
    hash_password,
    needs_rehash,
    verify_password,
)

logger = logging.getLogger("app.auth")

# 3-50 chars, starting alphanumeric, then alphanumeric/underscore/dot/dash.
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,49}$")


class AuthError(Exception):
    """User-facing account/authentication error.

    `status_code` is the HTTP status the API layer should map it to
    (409 for conflicts, 400 otherwise); pages render `message` directly.
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def get_user_by_username(db: Session, username: str) -> User | None:
    """Case-insensitive username lookup."""
    return db.scalar(
        select(User).where(func.lower(User.username) == (username or "").strip().lower())
    )


def register_user(
    db: Session,
    *,
    username: str,
    password: str,
    email: str | None = None,
    role: str = ROLE_MEMBER,
) -> User:
    """Validate and create a new account (password hashed with bcrypt).

    The `role` argument is NOT exposed through the public API schema -
    self-registration always yields "member". It exists for future
    admin-driven user management (Phase 6) and is whitelisted here.
    """
    username = (username or "").strip()
    email = (email or "").strip() or None

    if not USERNAME_RE.match(username):
        raise AuthError(
            "Username must be 3-50 characters, start with a letter or digit, "
            "and contain only letters, digits, underscore, dot or dash."
        )
    if not password or not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise AuthError(
            f"Password must be between {MIN_PASSWORD_LENGTH} and "
            f"{MAX_PASSWORD_LENGTH} characters."
        )
    if get_user_by_username(db, username) is not None:
        raise AuthError("This username is already taken.", status_code=409)
    if email is not None:
        email_taken = db.scalar(
            select(User).where(func.lower(User.email) == email.lower())
        )
        if email_taken is not None:
            raise AuthError("An account with this email already exists.", status_code=409)

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        hash_algorithm=BCRYPT,
        role=role if role in (ROLE_ADMIN, ROLE_MEMBER) else ROLE_MEMBER,
    )
    db.add(user)
    db.commit()
    logger.info("Registered user %r (role=%s)", user.username, user.role)
    return user


def authenticate(db: Session, *, username: str, password: str) -> User | None:
    """Verify credentials; return the user or None.

    Legacy SHA-256 hashes are transparently upgraded to bcrypt after a
    successful verification, so migrated accounts (admin/member from
    users.json) keep working and become secure on first login.
    """
    user = get_user_by_username(db, username)
    if user is None:
        # Burn bcrypt-equivalent time so a missing user is not
        # distinguishable from a wrong password by response timing.
        equalise_timing()
        return None

    if not verify_password(password, user.password_hash, user.hash_algorithm):
        return None

    if needs_rehash(user.hash_algorithm):
        user.password_hash = hash_password(password)
        user.hash_algorithm = BCRYPT
        db.add(user)
        db.commit()
        logger.info(
            "Upgraded legacy %s hash to bcrypt for user %r",
            LEGACY_SHA256,
            user.username,
        )
    return user
