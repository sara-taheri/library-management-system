"""Unit tests for the password hashing utilities."""
import hashlib

from app.utils.security import (
    BCRYPT,
    LEGACY_SHA256,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_bcrypt_hash_is_salted_and_verifiable():
    first = hash_password("s3cret-pass")
    second = hash_password("s3cret-pass")
    assert first != second  # random salt per hash
    assert first.startswith("$2b$")
    assert verify_password("s3cret-pass", first, BCRYPT) is True
    assert verify_password("wrong-pass", first, BCRYPT) is False


def test_legacy_sha256_verification():
    legacy_hash = hashlib.sha256(b"admin123").hexdigest()
    assert verify_password("admin123", legacy_hash, LEGACY_SHA256) is True
    assert verify_password("Admin123", legacy_hash, LEGACY_SHA256) is False


def test_known_legacy_hashes_from_users_json():
    """The demo accounts shipped in users.json must remain verifiable."""
    assert verify_password(
        "admin123",
        "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9",
        LEGACY_SHA256,
    )
    assert verify_password(
        "member123",
        "5600376e863d2f57a053518f324ad3840b0bc2348b573af281a7b7cbe7a228c6",
        LEGACY_SHA256,
    )


def test_needs_rehash_flags_legacy_only():
    assert needs_rehash(LEGACY_SHA256) is True
    assert needs_rehash(BCRYPT) is False


def test_unknown_algorithm_is_rejected():
    assert verify_password("x", "y", "md5") is False


def test_corrupt_bcrypt_hash_does_not_raise():
    assert verify_password("x", "not-a-valid-hash", BCRYPT) is False
