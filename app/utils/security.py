"""Password hashing and verification.

New accounts are hashed with **bcrypt** (salted, adaptive work factor).

Rows migrated from the legacy CLI storage (`users.json`) keep their
unsalted SHA-256 digests and are flagged ``hash_algorithm="legacy_sha256"``.
On the next *successful* login those accounts are transparently upgraded
to bcrypt (see :func:`app.services.auth_service.authenticate`), so no
existing user is locked out and weak hashes disappear over time.
"""
import hashlib
import hmac
import logging

import bcrypt

logger = logging.getLogger("app.security")

BCRYPT = "bcrypt"
LEGACY_SHA256 = "legacy_sha256"

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 72  # bcrypt silently truncates beyond 72 bytes

# Pre-computed bcrypt digest of a random dummy value. Verifying against it
# burns the same CPU time as a real check, so login responses for unknown
# usernames are not distinguishable by timing (username-enumeration
# hardening). Generated with: bcrypt.hashpw(b"...", bcrypt.gensalt())
DUMMY_BCRYPT_HASH = "$2b$12$TYK2E2uFxJ5OVlHMtq01sOp.htRCxG7kTGCqNhfmKYnU0Iz1QyDUO"


def hash_password(password: str) -> str:
    """Hash a plaintext password with a fresh random bcrypt salt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_bcrypt(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _verify_legacy_sha256(password: str, hashed: str) -> bool:
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    # Constant-time comparison against the stored hex digest.
    return hmac.compare_digest(digest, hashed or "")


def verify_password(password: str, hashed: str, algorithm: str = BCRYPT) -> bool:
    """Verify a password against a stored hash of the given algorithm."""
    if algorithm == BCRYPT:
        return _verify_bcrypt(password, hashed)
    if algorithm == LEGACY_SHA256:
        return _verify_legacy_sha256(password, hashed)
    logger.warning("Unknown password hash algorithm %r - rejecting", algorithm)
    return False


def needs_rehash(algorithm: str) -> bool:
    """True when the stored hash should be upgraded to bcrypt."""
    return algorithm != BCRYPT


def equalise_timing() -> None:
    """Perform a dummy bcrypt verification to mask user-existence timing."""
    _verify_bcrypt("timing-equalizer", DUMMY_BCRYPT_HASH)
