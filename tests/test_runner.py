"""Calendar runner tests (Checkpoint 4).

The runner is a pure service around the events table, so tests drive it
directly with a database session - including injected processors to
exercise failure handling. The last test runs the real CLI script as a
subprocess against the same database file.
"""
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.database import utcnow
from app.models import CalendarEvent, EventStatus, Loan, User
from app.services import event_service, loan_service
from app.services.runner_service import DEFAULT_PROCESSORS, find_due_events, run_due_tasks
from tests.conftest import make_user

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def runner_app(seeded_app):
    make_user(seeded_app, "alice", "alicepass123")
    make_user(seeded_app, "root", "rootpass123", role="admin")
    return seeded_app


@pytest.fixture()
def db(runner_app):
    with runner_app.state.session_factory() as session:
        yield session


def _user(db, username) -> User:
    return db.scalar(select(User).where(User.username == username))


def _make_event(db, username="alice", **overrides) -> CalendarEvent:
    """Create an event through the real service (scheduled_at included)."""
    data = {
        "title": "Task",
        "event_type": "reminder",
        "event_date": utcnow() - timedelta(hours=1),  # already due
    }
    data.update(overrides)
    return event_service.create_event(db, creator=_user(db, username), **data)


# ----------------------------------------------------------- due detection


def test_finds_only_due_pending_tasks(db):
    due = _make_event(db, title="Due reminder")
    future = _make_event(
        db, title="Future", event_date=utcnow() + timedelta(days=2)
    )
    general = _make_event(
        db, title="Personal", event_type="general"
    )
    cancelled = _make_event(db, title="Cancelled")
    event_service.cancel_event(db, event_id=cancelled.id, actor=_user(db, "alice"))
    completed = _make_event(db, title="Already done")
    completed.status = EventStatus.COMPLETED.value
    db.commit()

    found = find_due_events(db)
    assert [event.id for event in found] == [due.id]

    summary = run_due_tasks(db)
    assert summary["due"] == 1 and summary["succeeded"] == 1
    db.refresh(future)
    db.refresh(general)
    db.refresh(cancelled)
    db.refresh(completed)
    assert future.status == "pending" and future.executed_at is None
    assert general.status == "pending" and general.scheduled_at is None
    assert cancelled.status == "cancelled" and cancelled.executed_at is None
    assert completed.status == "completed"


# --------------------------------------------------------- success + repeat


def test_successful_execution_marks_completed(db):
    event = _make_event(db, title="Standup")
    run_time = utcnow() + timedelta(minutes=5)

    summary = run_due_tasks(db, now=run_time)
    assert summary["succeeded"] == 1 and summary["failed"] == 0

    db.refresh(event)
    assert event.status == EventStatus.COMPLETED.value
    assert event.executed_at == run_time  # execution time recorded
    assert "Reminder delivered to alice: Standup" == event.result_message


def test_completed_events_never_run_twice(db):
    event = _make_event(db)
    first = run_due_tasks(db)
    db.refresh(event)
    first_executed_at = event.executed_at
    first_message = event.result_message

    second = run_due_tasks(db, now=utcnow() + timedelta(hours=1))
    assert second["due"] == 0 and second["succeeded"] == 0
    db.refresh(event)
    assert event.status == EventStatus.COMPLETED.value
    assert event.executed_at == first_executed_at  # untouched
    assert event.result_message == first_message


def test_cancelled_events_are_ignored(db):
    event = _make_event(db)
    event_service.cancel_event(db, event_id=event.id, actor=_user(db, "alice"))

    summary = run_due_tasks(db)
    assert summary["due"] == 0
    db.refresh(event)
    assert event.status == EventStatus.CANCELLED.value
    assert event.executed_at is None


# ------------------------------------------------------------- failure path


def test_failed_task_stays_pending_and_is_retried(db):
    event = _make_event(db, title="Flaky")

    def broken_processor(_event):
        raise RuntimeError("smtp down")

    first_attempt = utcnow()
    summary = run_due_tasks(
        db, now=first_attempt, processors={"reminder": broken_processor}
    )
    assert summary["succeeded"] == 0 and summary["failed"] == 1

    db.refresh(event)
    assert event.status == EventStatus.PENDING.value  # retryable
    assert event.executed_at == first_attempt  # attempt recorded
    assert event.result_message == "ERROR: smtp down"

    # Next healthy run retries and completes it.
    retry_time = utcnow() + timedelta(minutes=10)
    summary2 = run_due_tasks(db, now=retry_time)
    assert summary2["succeeded"] == 1
    db.refresh(event)
    assert event.status == EventStatus.COMPLETED.value
    assert event.executed_at == retry_time
    assert event.result_message == "Reminder delivered to alice: Flaky"


def test_one_bad_task_does_not_block_the_others(db):
    first = _make_event(db, title="First", event_date=utcnow() - timedelta(hours=2))
    second = _make_event(db, title="Second", event_date=utcnow() - timedelta(hours=1))
    calls = []

    def flaky(event):
        calls.append(event.id)
        if event.title == "Second":
            raise RuntimeError("boom")
        return DEFAULT_PROCESSORS["reminder"](event)

    summary = run_due_tasks(db, processors={"reminder": flaky})
    assert summary["succeeded"] == 1 and summary["failed"] == 1
    assert calls == [first.id, second.id]  # each event processed exactly once

    db.refresh(first)
    db.refresh(second)
    assert first.status == "completed"
    assert second.status == "pending" and second.result_message == "ERROR: boom"

    # The retry run only touches the still-pending event.
    retry = run_due_tasks(db, now=utcnow() + timedelta(minutes=1))
    assert retry["due"] == 1 and retry["results"][0]["id"] == second.id
    db.refresh(first)
    db.refresh(second)
    assert first.status == "completed"
    assert second.status == "completed"


def test_unknown_event_type_is_left_alone(db):
    event = _make_event(db)
    event.event_type = "mystery"  # no processor knows this type
    db.commit()

    summary = run_due_tasks(db)
    assert summary["due"] == 0
    db.refresh(event)
    assert event.status == EventStatus.PENDING.value
    assert event.executed_at is None


# ------------------------------------------------- real flows + permissions


def test_book_return_reminder_follows_the_loan(db):
    alice = _user(db, "alice")
    loan = loan_service.borrow_book(db, user=alice, book_id=1)
    event = db.scalar(
        select(CalendarEvent).where(CalendarEvent.loan_id == loan.id)
    )
    assert event.status == "pending"
    assert event.scheduled_at == loan.due_at

    # Before the due date: nothing to do.
    early = run_due_tasks(db, now=loan.due_at - timedelta(days=1))
    assert early["due"] == 0

    # At the due date: reminder completes with loan details.
    summary = run_due_tasks(db, now=loan.due_at + timedelta(minutes=1))
    assert summary["succeeded"] == 1
    db.refresh(event)
    assert event.status == "completed"
    assert "Return reminder sent to alice" in event.result_message
    assert "Harry Potter" in event.result_message

    # A returned book cancels its reminder, so the runner skips it.
    loan2 = loan_service.borrow_book(db, user=alice, book_id=2)
    loan_service.return_book(db, loan_id=loan2.id, actor=alice)
    summary2 = run_due_tasks(db, now=utcnow() + timedelta(days=30))
    assert summary2["due"] == 0


def test_runner_handles_every_owner_and_admin_type(db):
    """The runner is system-level: it processes member and admin events
    alike in one pass (only owner/admin may *manage* events - the runner
    merely executes what they scheduled)."""
    _make_event(db, username="root", title="Inventory week", event_type="maintenance")
    _make_event(db, username="root", title="New opening hours", event_type="announcement")
    _make_event(db, username="alice", title="Nightly report", event_type="custom_task")

    summary = run_due_tasks(db)
    assert summary["due"] == 3 and summary["succeeded"] == 3
    messages = {row["title"]: row["result_message"] for row in summary["results"]}
    assert messages["Inventory week"] == "Maintenance notice posted: Inventory week"
    assert messages["New opening hours"] == (
        "Library announcement published: New opening hours"
    )
    assert messages["Nightly report"] == "Custom task executed: Nightly report"


# ------------------------------------------------------------- CLI script


def test_cli_script_processes_due_tasks(runner_app, db):
    event = _make_event(db, title="CLI reminder")
    url = str(runner_app.state.engine.url)

    proc = subprocess.run(
        [sys.executable, "scripts/run_calendar_tasks.py",
         "--database-url", url, "--verbose"],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 completed, 0 failed" in proc.stdout
    assert "CLI reminder" in proc.stdout
    assert "Reminder delivered to alice" in proc.stdout

    db.expire_all()
    db.refresh(event)
    assert event.status == EventStatus.COMPLETED.value

    # Running again is a clean no-op.
    proc2 = subprocess.run(
        [sys.executable, "scripts/run_calendar_tasks.py", "--database-url", url],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=120,
    )
    assert proc2.returncode == 0
    assert "No pending tasks due" in proc2.stdout


def test_cli_rejects_bad_now_argument(runner_app):
    url = str(runner_app.state.engine.url)
    proc = subprocess.run(
        [sys.executable, "scripts/run_calendar_tasks.py",
         "--database-url", url, "--now", "yesterday"],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=120,
    )
    assert proc.returncode == 2
    assert "Invalid --now" in proc.stdout


def test_cli_simulated_now(runner_app, db):
    """--now lets the runner be demoed without waiting for real due dates."""
    event = _make_event(
        db, title="October task", event_date=utcnow() + timedelta(days=20)
    )
    url = str(runner_app.state.engine.url)
    future = (utcnow() + timedelta(days=21)).strftime("%Y-%m-%dT%H:%M:%S")

    proc = subprocess.run(
        [sys.executable, "scripts/run_calendar_tasks.py",
         "--database-url", url, "--now", future],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=120,
    )
    assert proc.returncode == 0
    assert "1 completed" in proc.stdout
    db.expire_all()
    db.refresh(event)
    assert event.status == EventStatus.COMPLETED.value
