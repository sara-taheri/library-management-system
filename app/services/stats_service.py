"""Library statistics (shared by the admin API and dashboards).

`library_overview` returns the original count keys plus a small set of
dashboard-ready metrics derived from books, loans and events. All values
are cheap SQLite aggregates (plus one short recent-activity feed) so the
service stays a single function a student can explain.
"""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database import utcnow
from app.models import (
    Book,
    CalendarEvent,
    EventStatus,
    Loan,
    LoanStatus,
    User,
)

DUE_SOON_DAYS = 7
RECENT_ACTIVITY_LIMIT = 8


def library_overview(db: Session) -> dict:
    now = utcnow()
    due_soon_until = now + timedelta(days=DUE_SOON_DAYS)
    active = Loan.status == LoanStatus.ACTIVE.value

    def count(model, *where) -> int:
        stmt = select(func.count()).select_from(model)
        if where:
            stmt = stmt.where(*where)
        return db.scalar(stmt) or 0

    available_copies = db.scalar(
        select(func.coalesce(func.sum(Book.available_copies), 0)).where(
            Book.is_active.is_(True)
        )
    )
    borrowed_books = db.scalar(
        select(func.count(func.distinct(Loan.book_id))).where(active)
    )

    return {
        # Original keys - kept stable for the admin API schema.
        "users": count(User),
        "books": count(Book),
        "loans_total": count(Loan),
        "loans_active": count(Loan, active),
        "events": count(CalendarEvent),
        # Dashboard-ready extras (M1). Templates start using these in M3.
        "available_books": count(
            Book, Book.is_active.is_(True), Book.available_copies > 0
        ),
        "available_copies": int(available_copies or 0),
        "borrowed_books": borrowed_books or 0,
        "loans_overdue": count(Loan, active, Loan.due_at < now),
        "loans_due_soon": count(
            Loan, active, Loan.due_at >= now, Loan.due_at <= due_soon_until
        ),
        "events_upcoming": count(
            CalendarEvent,
            CalendarEvent.event_date >= now,
            CalendarEvent.status != EventStatus.CANCELLED.value,
        ),
        "recent_activity": _recent_activity(db),
    }


def _recent_activity(
    db: Session, limit: int = RECENT_ACTIVITY_LIMIT
) -> list[dict]:
    """Newest loans and events, merged and trimmed to `limit` rows."""
    loans = db.scalars(
        select(Loan)
        .options(joinedload(Loan.book), joinedload(Loan.user))
        .order_by(Loan.borrowed_at.desc(), Loan.id.desc())
        .limit(limit)
    ).all()
    events = db.scalars(
        select(CalendarEvent)
        .options(joinedload(CalendarEvent.creator))
        .order_by(CalendarEvent.created_at.desc(), CalendarEvent.id.desc())
        .limit(limit)
    ).all()

    items: list[dict] = []
    for loan in loans:
        if loan.status == LoanStatus.RETURNED.value and loan.returned_at is not None:
            action = "returned"
            when = loan.returned_at
        else:
            action = "borrowed"
            when = loan.borrowed_at
        items.append(
            {
                "kind": "loan",
                "id": loan.id,
                "action": action,
                "title": loan.book_title,
                "actor": loan.borrower,
                "at": when.isoformat(timespec="seconds"),
            }
        )
    for event in events:
        items.append(
            {
                "kind": "event",
                "id": event.id,
                "action": "scheduled",
                "title": event.title,
                "actor": event.creator_name,
                "at": event.created_at.isoformat(timespec="seconds"),
            }
        )
    items.sort(key=lambda row: (row["at"], row["kind"], row["id"]), reverse=True)
    return items[:limit]
