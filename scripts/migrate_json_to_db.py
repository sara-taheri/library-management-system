"""One-time migration: legacy JSON files -> SQLite database.

Reads the legacy CLI storage files (`books.json`, `users.json`,
`borrows.json`) and populates the new relational schema. The JSON files
are NEVER modified - they stay in the repository as a backup.

Migration rules:
- books:  `stock` -> `total_copies` = `available_copies` (best known values)
- users:  SHA-256 hashes are kept as-is with hash_algorithm="legacy_sha256";
          Phase 3 upgrades each account to bcrypt on its next login
- borrows -> loans: due_at = migration time + LOAN_PERIOD_DAYS.
          Records pointing at a missing user or book (e.g. the legacy
          orphan "sara_admin" row) are reported and skipped.

Usage (from the repository root):
    python scripts/migrate_json_to_db.py           # migrate into DATABASE_URL
    python scripts/migrate_json_to_db.py --reset   # rebuild tables first
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, make_engine, make_session_factory, utcnow  # noqa: E402
from app.models import Book, Loan, LoanStatus, User  # noqa: E402


def _read_json(path: Path) -> list:
    if not path.exists():
        print(f"  ! {path.name} not found - skipping")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"  ! {path.name} is not valid JSON ({exc}) - skipping")
        return []
    if not isinstance(data, list):
        print(f"  ! {path.name} does not contain a list - skipping")
        return []
    return data


def migrate(
    books_file: str | Path,
    users_file: str | Path,
    borrows_file: str | Path,
    database_url: str | None = None,
    loan_period_days: int | None = None,
    reset: bool = False,
) -> dict:
    """Run the migration and return a summary dict.

    Raises SystemExit if the target database already contains data and
    `reset` was not requested (protects against accidental double runs).
    """
    database_url = database_url or settings.database_url
    if loan_period_days is None:
        loan_period_days = settings.loan_period_days

    if database_url.startswith("sqlite:///"):
        db_path = database_url.removeprefix("sqlite:///")
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = make_engine(database_url)
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    summary = {
        "books": 0,
        "users": 0,
        "loans": 0,
        "skipped_orphan_borrows": 0,
        "skipped_invalid_rows": 0,
    }

    books_raw = _read_json(Path(books_file))
    users_raw = _read_json(Path(users_file))
    borrows_raw = _read_json(Path(borrows_file))

    with session_factory() as db:
        already_has_data = (
            db.scalar(select(Book).limit(1)) is not None
            or db.scalar(select(User).limit(1)) is not None
        )
        if already_has_data and not reset:
            raise SystemExit(
                "Target database already contains data. "
                "Re-run with --reset to rebuild it (JSON files are never modified)."
            )

        # --- users -----------------------------------------------------
        username_to_id: dict[str, int] = {}
        for row in users_raw:
            if not all(key in row for key in ("username", "password", "role")):
                summary["skipped_invalid_rows"] += 1
                print(f"  ! user row missing required keys, skipped: {row!r}")
                continue
            username = str(row["username"]).strip()
            if not username or username.lower() in username_to_id:
                summary["skipped_invalid_rows"] += 1
                print(f"  ! duplicate/empty username skipped: {username!r}")
                continue
            user = User(
                username=username,
                password_hash=str(row["password"]),
                hash_algorithm="legacy_sha256",
                role=str(row["role"]).strip().lower() or "member",
            )
            db.add(user)
            db.flush()
            username_to_id[username.lower()] = user.id
            summary["users"] += 1

        # --- books -----------------------------------------------------
        legacy_to_new_book_id: dict[int, int] = {}
        used_ids: set[int] = set()
        for row in books_raw:
            if not all(key in row for key in ("id", "title", "author", "stock")):
                summary["skipped_invalid_rows"] += 1
                print(f"  ! book row missing required keys, skipped: {row!r}")
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
            # Preserve the legacy integer IDs where possible so existing
            # references (and muscle memory) keep working.
            if legacy_id is not None and legacy_id > 0 and legacy_id not in used_ids:
                book.id = legacy_id
                used_ids.add(legacy_id)
            elif legacy_id is not None:
                print(
                    f"  ! duplicate/invalid book id {legacy_id} for "
                    f"'{book.title}' - assigning a new id"
                )
            db.add(book)
            db.flush()
            if legacy_id is not None:
                legacy_to_new_book_id[legacy_id] = book.id
            summary["books"] += 1

        # --- borrows -> loans ------------------------------------------
        now = utcnow()
        for row in borrows_raw:
            username = str(row.get("username", "")).strip().lower()
            try:
                legacy_book_id: int | None = int(row.get("book_id"))
            except (TypeError, ValueError):
                legacy_book_id = None

            user_id = username_to_id.get(username)
            book_id = legacy_to_new_book_id.get(legacy_book_id)  # type: ignore[arg-type]

            if user_id is None or book_id is None:
                summary["skipped_orphan_borrows"] += 1
                print(
                    f"  ! orphan borrow skipped: username={row.get('username')!r} "
                    f"book_id={row.get('book_id')!r} (no matching user/book)"
                )
                continue

            db.add(
                Loan(
                    user_id=user_id,
                    book_id=book_id,
                    borrowed_at=now,
                    due_at=now + timedelta(days=loan_period_days),
                    status=LoanStatus.ACTIVE.value,
                )
            )
            summary["loans"] += 1

        db.commit()

    engine.dispose()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate legacy JSON data into the SQLite database."
    )
    parser.add_argument("--books", default=str(REPO_ROOT / "books.json"))
    parser.add_argument("--users", default=str(REPO_ROOT / "users.json"))
    parser.add_argument("--borrows", default=str(REPO_ROOT / "borrows.json"))
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL (default: the configured app database)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and rebuild the tables before migrating (database only; "
        "JSON files are never modified)",
    )
    args = parser.parse_args()

    target = args.database_url or settings.database_url
    print(f"Migrating legacy JSON data -> {target}")
    summary = migrate(
        args.books,
        args.users,
        args.borrows,
        database_url=args.database_url,
        reset=args.reset,
    )
    print("Migration summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print("Done. Legacy JSON files were left untouched.")


if __name__ == "__main__":
    main()
