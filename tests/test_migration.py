"""Tests for the legacy JSON -> SQLite migration script."""
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.database import make_engine, make_session_factory
from app.models import Book, Loan, User
from scripts.migrate_json_to_db import migrate

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _inspect(database_url: str):
    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        books = db.scalars(select(Book)).all()
        users = db.scalars(select(User)).all()
        loans = db.scalars(select(Loan)).all()
    engine.dispose()
    return books, users, loans


def test_migrate_synthetic_data(tmp_path):
    books_file = _write_json(
        tmp_path / "books.json",
        [{"id": 10, "title": "Dune", "author": "Frank Herbert", "stock": 2}],
    )
    users_file = _write_json(
        tmp_path / "users.json",
        [{"username": "alice", "password": "abc123hash", "role": "member"}],
    )
    borrows_file = _write_json(
        tmp_path / "borrows.json",
        [
            {"username": "alice", "book_id": 10},   # valid -> becomes a loan
            {"username": "ghost", "book_id": 10},   # orphan user -> skipped
            {"username": "alice", "book_id": 999},  # orphan book -> skipped
        ],
    )
    url = f"sqlite:///{tmp_path / 'migrated.db'}"

    summary = migrate(books_file, users_file, borrows_file, database_url=url)

    assert summary == {
        "books": 1,
        "users": 1,
        "loans": 1,
        "skipped_orphan_borrows": 2,
        "skipped_invalid_rows": 0,
    }

    books, users, loans = _inspect(url)
    assert books[0].id == 10  # legacy id preserved
    assert books[0].total_copies == 2
    assert books[0].available_copies == 2
    assert users[0].username == "alice"
    assert users[0].password_hash == "abc123hash"
    assert users[0].hash_algorithm == "legacy_sha256"  # flagged for bcrypt upgrade
    assert len(loans) == 1
    assert (loans[0].due_at - loans[0].borrowed_at).days == 14
    assert loans[0].status == "active"


def test_migrate_real_repository_data(tmp_path):
    """Migrate the actual books.json/users.json/borrows.json from the repo."""
    books_file = REPO_ROOT / "books.json"
    if not books_file.exists():
        pytest.skip("legacy JSON data files not present")

    url = f"sqlite:///{tmp_path / 'real.db'}"
    summary = migrate(
        books_file,
        REPO_ROOT / "users.json",
        REPO_ROOT / "borrows.json",
        database_url=url,
    )

    assert summary["books"] == 3
    assert summary["users"] == 2
    # The known orphan record ("sara_admin") must be skipped, not fatal.
    assert summary["loans"] == 0
    assert summary["skipped_orphan_borrows"] == 1

    books, users, _ = _inspect(url)
    assert {b.title for b in books} == {"Harry Potter", "the notebook", "Hamlet"}
    assert {u.username for u in users} == {"admin", "member"}
    assert next(u for u in users if u.username == "admin").role == "admin"


def test_migrate_refuses_to_overwrite_existing_data(tmp_path):
    books_file = _write_json(tmp_path / "books.json", [])
    users_file = _write_json(
        tmp_path / "users.json",
        [{"username": "bob", "password": "hash", "role": "member"}],
    )
    borrows_file = _write_json(tmp_path / "borrows.json", [])
    url = f"sqlite:///{tmp_path / 'twice.db'}"

    migrate(books_file, users_file, borrows_file, database_url=url)
    with pytest.raises(SystemExit):
        migrate(books_file, users_file, borrows_file, database_url=url)

    # --reset makes the re-run succeed and keeps the data consistent.
    summary = migrate(books_file, users_file, borrows_file, database_url=url, reset=True)
    assert summary["users"] == 1


def test_migrate_handles_missing_and_invalid_files(tmp_path):
    books_file = _write_json(
        tmp_path / "books.json",
        [
            {"id": 1, "title": "Valid", "author": "Author", "stock": 1},
            {"id": 2, "title": "No stock field"},          # invalid -> skipped
            {"id": 1, "title": "Dup Id", "author": "A", "stock": 1},  # dup id -> new id
        ],
    )
    missing_users = tmp_path / "does_not_exist.json"
    missing_borrows = tmp_path / "also_missing.json"
    url = f"sqlite:///{tmp_path / 'edge.db'}"

    summary = migrate(books_file, missing_users, missing_borrows, database_url=url)

    assert summary["books"] == 2
    assert summary["users"] == 0
    assert summary["skipped_invalid_rows"] == 1
    books, _, _ = _inspect(url)
    ids = sorted(b.id for b in books)
    assert len(set(ids)) == 2  # duplicate legacy id got a fresh unique id
