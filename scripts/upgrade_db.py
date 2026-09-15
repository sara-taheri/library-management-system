"""In-place, idempotent schema upgrades for an existing data/library.db.

SQLAlchemy's create_all() only creates MISSING TABLES - it never alters
existing ones. When a checkpoint adds a column to an existing table, run
this script once:

    python scripts/upgrade_db.py

It inspects the current SQLite schema and applies the minimal ALTER
statements needed. It is safe to run repeatedly and never deletes data.

Upgrade history:
- Checkpoint 1: books.is_active (soft-delete flag)
- Checkpoint 3: events table modernised in place (Phase-2 placeholder ->
  calendar/runner schema): user_id -> created_by, start_at -> event_date,
  end_at/all_day/updated_at dropped, book_id/status/scheduled_at/
  executed_at/result_message added, event_type values renamed
  (due_date -> book_return, library -> announcement). Rows are preserved.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import inspect, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, make_engine  # noqa: E402
import app.models  # noqa: F401,E402  (register all models on Base.metadata)


def upgrade(database_url: str | None = None) -> list[str]:
    """Apply all pending schema upgrades; return a human-readable report."""
    database_url = database_url or settings.database_url
    engine = make_engine(database_url)
    report: list[str] = []

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    def columns(table: str) -> set[str]:
        return {c["name"] for c in inspector.get_columns(table)}

    with engine.begin() as conn:
        # --- Checkpoint 1: books.is_active ---------------------------
        if "books" in tables and "is_active" not in columns("books"):
            conn.execute(
                text(
                    "ALTER TABLE books ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"
                )
            )
            report.append("books: added column is_active (default TRUE)")

        # --- Checkpoint 3: events table modernisation ----------------
        if "events" in tables:
            cols = columns("events")
            looks_legacy = bool(
                {"user_id", "start_at", "end_at", "all_day", "updated_at"} & cols
            )
            if looks_legacy:
                row_count = conn.execute(
                    text("SELECT COUNT(*) FROM events")
                ).scalar()
                if "user_id" in cols and "created_by" not in cols:
                    conn.execute(
                        text("ALTER TABLE events RENAME COLUMN user_id TO created_by")
                    )
                if "start_at" in cols and "event_date" not in cols:
                    conn.execute(
                        text("ALTER TABLE events RENAME COLUMN start_at TO event_date")
                    )
                additions = (
                    ("book_id", "ALTER TABLE events ADD COLUMN book_id INTEGER REFERENCES books(id)"),
                    ("status", "ALTER TABLE events ADD COLUMN status VARCHAR(12) NOT NULL DEFAULT 'pending'"),
                    ("scheduled_at", "ALTER TABLE events ADD COLUMN scheduled_at DATETIME"),
                    ("executed_at", "ALTER TABLE events ADD COLUMN executed_at DATETIME"),
                    ("result_message", "ALTER TABLE events ADD COLUMN result_message TEXT"),
                )
                for column_name, ddl in additions:
                    if column_name not in cols:
                        conn.execute(text(ddl))
                for old_column in ("end_at", "all_day", "updated_at"):
                    if old_column in cols:
                        conn.execute(
                            text(f"ALTER TABLE events DROP COLUMN {old_column}")
                        )
                # Rename event_type values and give task-like rows a
                # schedule so the runner (Checkpoint 4) can find them.
                conn.execute(
                    text("UPDATE events SET event_type = 'book_return' WHERE event_type = 'due_date'")
                )
                conn.execute(
                    text("UPDATE events SET event_type = 'announcement' WHERE event_type = 'library'")
                )
                conn.execute(
                    text(
                        "UPDATE events SET scheduled_at = event_date "
                        "WHERE scheduled_at IS NULL AND event_type != 'general'"
                    )
                )
                report.append(
                    f"events: modernised Phase-2 schema in place "
                    f"({row_count} row(s) preserved)"
                )
            # Ensure indexes exist for the (possibly renamed) columns and
            # drop the duplicates left behind by the column renames
            # (SQLite keeps the old index names pointing at the new names).
            for legacy_index in ("ix_events_user_id", "ix_events_start_at"):
                conn.execute(text(f"DROP INDEX IF EXISTS {legacy_index}"))
            for column_name in (
                "created_by", "event_date", "event_type", "status", "scheduled_at"
            ):
                conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS ix_events_{column_name} "
                        f"ON events ({column_name})"
                    )
                )

    # Recreate any tables that do not exist yet (never touches existing data).
    Base.metadata.create_all(engine)
    engine.dispose()

    if not report:
        report.append("no changes needed - schema is up to date")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    target = args.database_url or settings.database_url
    print(f"Upgrading database schema: {target}")
    for line in upgrade(args.database_url):
        print(f"  - {line}")
    print("Done.")


if __name__ == "__main__":
    main()
