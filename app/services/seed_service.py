"""Idempotent first-boot seed for an empty SQLite database.

Called from ``create_app()`` after ``create_all()``. Rules:

- If there are no books, insert the sample catalog from ``books.json``.
- If there are no users, insert classroom demo accounts with **bcrypt**
  hashes (never plaintext, never the legacy SHA-256 JSON hashes).
- If either table already has rows, that table is left untouched.
- ``borrows.json`` is never imported here (the orphan legacy row would
  be misleading on a fresh install). Use ``scripts/migrate_json_to_db.py``
  for an explicit full migration.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.models import Book, User
from app.models.user import ROLE_ADMIN, ROLE_MEMBER
from app.utils.security import BCRYPT, hash_password

logger = logging.getLogger("app.seed")

DEFAULT_BOOKS_FILE = BASE_DIR / "books.json"

# Classroom demo logins. Plaintext exists only in this module (and README)
# so bcrypt can be computed at seed time. The database stores hashes.
DEMO_ADMIN_USERNAME = "admin"
DEMO_ADMIN_PASSWORD = "admin123"
DEMO_MEMBER_USERNAME = "member"
DEMO_MEMBER_PASSWORD = "member123"


def seed_if_empty(
    db: Session, books_file: str | Path | None = None
) -> dict:
    """Fill empty books/users tables. Safe to call on every startup."""
    summary = {"books": 0, "users": 0}
    summary["books"] = _seed_books_if_empty(db, books_file)
    summary["users"] = _seed_users_if_empty(db)
    return summary


def _seed_books_if_empty(db: Session, books_file: str | Path | None) -> int:
    if db.scalar(select(Book.id).limit(1)) is not None:
        return 0

    path = Path(books_file) if books_file is not None else DEFAULT_BOOKS_FILE
    rows = _read_books_json(path)
    if not rows:
        return 0

    added = 0
    used_ids: set[int] = set()
    for row in rows:
        if not all(key in row for key in ("id", "title", "author", "stock")):
            continue
        try:
            stock = max(0, int(row["stock"]))
        except (TypeError, ValueError):
            stock = 0
        try:
            legacy_id: int | None = int(row["id"])
        except (TypeError, ValueError):
            legacy_id = None

        book = Book(
            title=str(row["title"]).strip(),
            author=str(row["author"]).strip(),
            total_copies=stock,
            available_copies=stock,
        )
        if legacy_id is not None and legacy_id > 0 and legacy_id not in used_ids:
            book.id = legacy_id
            used_ids.add(legacy_id)
        db.add(book)
        db.flush()
        added += 1

    db.commit()
    logger.info("First-boot seed: inserted %s sample book(s)", added)
    return added


def _seed_users_if_empty(db: Session) -> int:
    if db.scalar(select(User.id).limit(1)) is not None:
        return 0

    demo = (
        (DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, ROLE_ADMIN),
        (DEMO_MEMBER_USERNAME, DEMO_MEMBER_PASSWORD, ROLE_MEMBER),
    )
    for username, password, role in demo:
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                hash_algorithm=BCRYPT,
                role=role,
            )
        )
    db.commit()
    logger.info("First-boot seed: inserted %s demo user(s) (bcrypt)", len(demo))
    return len(demo)


def _read_books_json(path: Path) -> list:
    if not path.exists():
        logger.warning("Seed books file not found: %s", path)
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning("Seed books file is not valid JSON (%s)", exc)
        return []
    if not isinstance(data, list):
        return []
    return data
