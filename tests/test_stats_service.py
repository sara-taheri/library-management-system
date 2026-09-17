"""Direct unit tests for stats_service.library_overview."""
from datetime import timedelta

from sqlalchemy import select

from app.database import utcnow
from app.models import Book, CalendarEvent, EventStatus, Loan, LoanStatus, User
from app.services.stats_service import DUE_SOON_DAYS, library_overview
from tests.conftest import make_user

ORIGINAL_KEYS = {"users", "books", "loans_total", "loans_active", "events"}
DASHBOARD_KEYS = {
    "available_books",
    "available_copies",
    "borrowed_books",
    "loans_overdue",
    "loans_due_soon",
    "events_upcoming",
    "recent_activity",
}


def test_overview_empty_library(app):
    with app.state.session_factory() as db:
        stats = library_overview(db)

    assert ORIGINAL_KEYS <= set(stats)
    assert DASHBOARD_KEYS <= set(stats)
    assert stats["users"] == 0
    assert stats["books"] == 0
    assert stats["available_books"] == 0
    assert stats["available_copies"] == 0
    assert stats["borrowed_books"] == 0
    assert stats["loans_total"] == 0
    assert stats["loans_active"] == 0
    assert stats["loans_overdue"] == 0
    assert stats["loans_due_soon"] == 0
    assert stats["events"] == 0
    assert stats["events_upcoming"] == 0
    assert stats["recent_activity"] == []


def test_overview_seeded_catalog_counts(seeded_app):
    """Seeded books: Harry Potter 4/5, Notebook 4/4, Hamlet 7/7. No loans."""
    with seeded_app.state.session_factory() as db:
        stats = library_overview(db)

    assert stats["books"] == 3
    assert stats["available_books"] == 3
    assert stats["available_copies"] == 15
    assert stats["borrowed_books"] == 0
    assert stats["loans_total"] == 0
    assert stats["events"] == 0


def test_overview_inactive_book_is_not_available(app):
    with app.state.session_factory() as db:
        db.add(
            Book(
                title="Retired",
                author="Anon",
                total_copies=2,
                available_copies=2,
                is_active=False,
            )
        )
        db.add(
            Book(
                title="On the shelf",
                author="Anon",
                total_copies=3,
                available_copies=3,
                is_active=True,
            )
        )
        db.commit()
        stats = library_overview(db)

    assert stats["books"] == 2
    assert stats["available_books"] == 1
    assert stats["available_copies"] == 3


def test_overview_loan_metrics(app):
    make_user(app, "alice", "password123")
    now = utcnow()
    with app.state.session_factory() as db:
        alice = db.scalar(select(User).where(User.username == "alice"))
        overdue_book = Book(
            title="Overdue Book", author="A", total_copies=1, available_copies=0
        )
        soon_book = Book(
            title="Due Soon Book", author="A", total_copies=1, available_copies=0
        )
        later_book = Book(
            title="Later Book", author="A", total_copies=1, available_copies=0
        )
        returned_book = Book(
            title="Returned Book", author="A", total_copies=1, available_copies=1
        )
        db.add_all([overdue_book, soon_book, later_book, returned_book])
        db.flush()
        db.add_all(
            [
                Loan(
                    user_id=alice.id,
                    book_id=overdue_book.id,
                    borrowed_at=now - timedelta(days=20),
                    due_at=now - timedelta(days=2),
                    status=LoanStatus.ACTIVE.value,
                ),
                Loan(
                    user_id=alice.id,
                    book_id=soon_book.id,
                    borrowed_at=now - timedelta(days=7),
                    due_at=now + timedelta(days=3),
                    status=LoanStatus.ACTIVE.value,
                ),
                Loan(
                    user_id=alice.id,
                    book_id=later_book.id,
                    borrowed_at=now,
                    due_at=now + timedelta(days=DUE_SOON_DAYS + 1),
                    status=LoanStatus.ACTIVE.value,
                ),
                Loan(
                    user_id=alice.id,
                    book_id=returned_book.id,
                    borrowed_at=now - timedelta(days=10),
                    due_at=now - timedelta(days=1),
                    returned_at=now - timedelta(hours=1),
                    status=LoanStatus.RETURNED.value,
                ),
            ]
        )
        db.commit()
        stats = library_overview(db)

    assert stats["users"] == 1
    assert stats["books"] == 4
    assert stats["loans_total"] == 4
    assert stats["loans_active"] == 3
    assert stats["loans_overdue"] == 1
    assert stats["loans_due_soon"] == 1
    assert stats["borrowed_books"] == 3
    assert stats["available_books"] == 1  # only the returned copy is free
    assert stats["available_copies"] == 1


def test_overview_upcoming_events_excludes_past_and_cancelled(app):
    make_user(app, "alice", "password123")
    now = utcnow()
    with app.state.session_factory() as db:
        alice = db.scalar(select(User).where(User.username == "alice"))
        db.add_all(
            [
                CalendarEvent(
                    created_by=alice.id,
                    title="Future talk",
                    event_date=now + timedelta(days=2),
                    event_type="general",
                ),
                CalendarEvent(
                    created_by=alice.id,
                    title="Already happened",
                    event_date=now - timedelta(days=2),
                    event_type="general",
                ),
                CalendarEvent(
                    created_by=alice.id,
                    title="Cancelled future",
                    event_date=now + timedelta(days=3),
                    event_type="general",
                    status=EventStatus.CANCELLED.value,
                ),
            ]
        )
        db.commit()
        stats = library_overview(db)

    assert stats["events"] == 3
    assert stats["events_upcoming"] == 1


def test_overview_recent_activity_merges_loans_and_events(app):
    make_user(app, "alice", "password123")
    now = utcnow()
    with app.state.session_factory() as db:
        alice = db.scalar(select(User).where(User.username == "alice"))
        book = Book(
            title="Activity Book", author="A", total_copies=1, available_copies=0
        )
        db.add(book)
        db.flush()
        db.add(
            Loan(
                user_id=alice.id,
                book_id=book.id,
                borrowed_at=now,
                due_at=now + timedelta(days=14),
                status=LoanStatus.ACTIVE.value,
            )
        )
        db.add(
            CalendarEvent(
                created_by=alice.id,
                title="Club meeting",
                event_date=now + timedelta(days=1),
                event_type="general",
            )
        )
        db.commit()
        stats = library_overview(db)

    kinds = {item["kind"] for item in stats["recent_activity"]}
    titles = {item["title"] for item in stats["recent_activity"]}
    assert kinds == {"loan", "event"}
    assert "Activity Book" in titles
    assert "Club meeting" in titles
    for item in stats["recent_activity"]:
        assert {"kind", "id", "action", "title", "actor", "at"} <= set(item)
        assert item["actor"] == "alice"
