"""scripts/upgrade_db.py tests: in-place, idempotent schema upgrades.

The upgrade path matters because create_all() never alters existing
tables - a real data/library.db from an earlier phase must gain new
columns without losing any rows.
"""
import sqlite3

from scripts.upgrade_db import upgrade

LEGACY_BOOKS_DDL = """
CREATE TABLE books (
    id INTEGER NOT NULL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    author VARCHAR(255) NOT NULL,
    isbn VARCHAR(20),
    genre VARCHAR(100),
    description TEXT,
    total_copies INTEGER NOT NULL,
    available_copies INTEGER NOT NULL,
    created_at DATETIME NOT NULL
)
"""


def _legacy_db(tmp_path) -> str:
    """A database shaped exactly like the Phase-2 schema (no is_active)."""
    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_file)
    conn.execute(LEGACY_BOOKS_DDL)
    conn.execute(
        "INSERT INTO books (id, title, author, total_copies, available_copies, created_at) "
        "VALUES (1, 'Old Book', 'Old Author', 2, 1, '2024-01-01 00:00:00')"
    )
    conn.commit()
    conn.close()
    return f"sqlite:///{db_file}"


def test_upgrade_adds_is_active_and_preserves_rows(tmp_path):
    url = _legacy_db(tmp_path)
    report = upgrade(url)
    assert any("is_active" in line for line in report)

    conn = sqlite3.connect(tmp_path / "legacy.db")
    columns = [row[1] for row in conn.execute("PRAGMA table_info(books)")]
    assert "is_active" in columns
    row = conn.execute(
        "SELECT title, available_copies, is_active FROM books WHERE id = 1"
    ).fetchone()
    conn.close()
    assert row == ("Old Book", 1, 1)  # data preserved, defaults to active


def test_upgrade_is_idempotent(tmp_path):
    url = _legacy_db(tmp_path)
    upgrade(url)
    second_report = upgrade(url)
    assert second_report == ["no changes needed - schema is up to date"]


def test_upgrade_creates_missing_tables(tmp_path):
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    upgrade(url)
    conn = sqlite3.connect(tmp_path / "fresh.db")
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    assert {"users", "books", "loans", "events"} <= tables


# ------------------------------------------------------- events (CP3)

LEGACY_EVENTS_DDL = """
CREATE TABLE events (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title VARCHAR(200) NOT NULL,
    description TEXT,
    start_at DATETIME NOT NULL,
    end_at DATETIME,
    all_day BOOLEAN NOT NULL DEFAULT 0,
    event_type VARCHAR(20) NOT NULL DEFAULT 'general',
    loan_id INTEGER REFERENCES loans(id),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""


def _legacy_events_db(tmp_path) -> str:
    """A database with the Phase-2 events schema and two sample rows."""
    db_file = tmp_path / "legacy_events.db"
    conn = sqlite3.connect(db_file)
    conn.execute(LEGACY_EVENTS_DDL)
    conn.execute(
        "INSERT INTO events (id, user_id, title, start_at, all_day, event_type, created_at, updated_at) "
        "VALUES (1, 7, 'Return Dune', '2026-10-01 12:00:00', 0, 'due_date', "
        "'2026-09-01 00:00:00', '2026-09-01 00:00:00')"
    )
    conn.execute(
        "INSERT INTO events (id, user_id, title, start_at, all_day, event_type, created_at, updated_at) "
        "VALUES (2, 7, 'Reading club', '2026-10-05 18:00:00', 0, 'general', "
        "'2026-09-01 00:00:00', '2026-09-01 00:00:00')"
    )
    conn.commit()
    conn.close()
    return f"sqlite:///{db_file}"


def test_upgrade_modernises_events_table(tmp_path):
    url = _legacy_events_db(tmp_path)
    report = upgrade(url)
    assert any("events: modernised" in line for line in report)

    conn = sqlite3.connect(tmp_path / "legacy_events.db")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(events)")]
    for expected in (
        "created_by", "event_date", "status", "scheduled_at",
        "executed_at", "result_message", "book_id",
    ):
        assert expected in cols
    for removed in ("user_id", "start_at", "end_at", "all_day", "updated_at"):
        assert removed not in cols

    row = conn.execute(
        "SELECT created_by, title, event_date, event_type, status, scheduled_at "
        "FROM events WHERE id = 1"
    ).fetchone()
    assert row[0] == 7 and row[1] == "Return Dune"  # data preserved
    assert row[3] == "book_return"  # due_date renamed
    assert row[4] == "pending"  # runner default
    assert row[5] == row[2]  # task scheduled for its event date

    general = conn.execute(
        "SELECT event_type, scheduled_at FROM events WHERE id = 2"
    ).fetchone()
    assert general == ("general", None)  # personal events are not tasks
    conn.close()


def test_upgrade_events_migration_is_idempotent(tmp_path):
    url = _legacy_events_db(tmp_path)
    upgrade(url)
    second_report = upgrade(url)
    assert second_report == ["no changes needed - schema is up to date"]
