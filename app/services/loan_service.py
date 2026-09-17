"""Borrowing/returning business logic (Checkpoint 2).

One code path shared by the JSON API and the server-rendered pages:

- borrow: 404 unknown book, 400 deactivated book, 409 when the member
  already has an active loan for the same book, 409 when no copy is
  free. On success the availability counter is decremented and a
  "book due" calendar event is scheduled automatically.
- return: owner-or-admin only (403 otherwise), 409 when already
  returned. Availability is restored and the auto-created due-date
  event is cleared.

The calendar event uses the EXISTING CalendarEvent table - Checkpoint 3
modernises that model in place (no second calendar system).
"""
import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import utcnow
from app.models import (
    Book,
    CalendarEvent,
    EventStatus,
    EventType,
    Loan,
    LoanStatus,
    User,
)

logger = logging.getLogger("app.loans")


class LoanError(Exception):
    """User-facing loan error (status_code maps to HTTP)."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ------------------------------------------------------------------- reads


def get_loan(db: Session, loan_id: int) -> Loan | None:
    return db.get(Loan, loan_id)


def active_loan_for(db: Session, user_id: int, book_id: int) -> Loan | None:
    """The user's currently active loan for a specific book, if any."""
    return db.scalar(
        select(Loan).where(
            Loan.user_id == user_id,
            Loan.book_id == book_id,
            Loan.status == LoanStatus.ACTIVE.value,
        )
    )


def list_loans(
    db: Session,
    *,
    user_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[Loan], int, int]:
    """Return (items, total, pages); newest loans first."""
    stmt = select(Loan)
    if user_id is not None:
        stmt = stmt.where(Loan.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Loan.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db.scalars(
            stmt.order_by(Loan.borrowed_at.desc(), Loan.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    pages = max(1, -(-total // page_size))
    return items, total, pages


def activity_on_date(
    db: Session, day: date, *, user_id: int | None = None
) -> dict:
    """Loans due / borrowed / returned on a calendar day.

    ``user_id=None`` means every member (admin briefing). Pass a member
    id to restrict the lists to that member's own loans. Guests should
    not call this - the page layer skips it.
    """
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)

    def _load(stmt):
        if user_id is not None:
            stmt = stmt.where(Loan.user_id == user_id)
        return list(
            db.scalars(
                stmt.options(joinedload(Loan.book), joinedload(Loan.user))
                .order_by(Loan.id)
            )
            .unique()
            .all()
        )

    due = _load(
        select(Loan).where(
            Loan.status == LoanStatus.ACTIVE.value,
            Loan.due_at >= start,
            Loan.due_at < end,
        )
    )
    borrowed = _load(
        select(Loan).where(Loan.borrowed_at >= start, Loan.borrowed_at < end)
    )
    returned = _load(
        select(Loan).where(
            Loan.returned_at.isnot(None),
            Loan.returned_at >= start,
            Loan.returned_at < end,
        )
    )
    return {"due": due, "borrowed": borrowed, "returned": returned}


# ------------------------------------------------------------------ writes


def borrow_book(db: Session, *, user: User, book_id: int, now=None) -> Loan:
    now = now or utcnow()
    book = db.get(Book, book_id)
    if book is None:
        raise LoanError("Book not found.", status_code=404)
    if not book.is_active:
        raise LoanError(
            f"'{book.title}' is not in the active catalog anymore.", status_code=400
        )
    if active_loan_for(db, user.id, book.id) is not None:
        raise LoanError(
            f"You already borrowed '{book.title}' and have not returned it yet.",
            status_code=409,
        )
    if book.available_copies < 1:
        raise LoanError(
            f"All copies of '{book.title}' are currently on loan.", status_code=409
        )

    due_at = now + timedelta(days=settings.loan_period_days)
    loan = Loan(
        user_id=user.id,
        book_id=book.id,
        borrowed_at=now,
        due_at=due_at,
        status=LoanStatus.ACTIVE.value,
    )
    db.add(loan)
    book.available_copies -= 1
    db.flush()  # assign loan.id so the event can reference it

    # Automatically schedule the book-return reminder on the shared
    # calendar. It is a pending runner task: scheduled_at == due_at, so
    # the Checkpoint-4 runner picks it up when the book falls due.
    db.add(
        CalendarEvent(
            created_by=user.id,
            title=f"Return '{book.title}'",
            description=(
                f"Due date for your loan of '{book.title}' "
                f"(borrowed {now:%Y-%m-%d})."
            ),
            event_date=due_at,
            event_type=EventType.BOOK_RETURN.value,
            book_id=book.id,
            loan_id=loan.id,
            status=EventStatus.PENDING.value,
            scheduled_at=due_at,
        )
    )
    db.commit()
    logger.info(
        "User %s borrowed book %s (loan %s, due %s)",
        user.username, book.id, loan.id, due_at.date(),
    )
    return loan


def return_book(db: Session, *, loan_id: int, actor: User, now=None) -> Loan:
    now = now or utcnow()
    loan = db.get(Loan, loan_id)
    if loan is None:
        raise LoanError("Loan not found.", status_code=404)
    if not (actor.is_admin or loan.user_id == actor.id):
        raise LoanError("You can only return your own loans.", status_code=403)
    if loan.status == LoanStatus.RETURNED.value:
        raise LoanError("This loan was already returned.", status_code=409)

    loan.returned_at = now
    loan.status = LoanStatus.RETURNED.value

    book = db.get(Book, loan.book_id)
    if book is not None:  # defensive; hard deletes are blocked while loans exist
        book.available_copies = min(book.total_copies, book.available_copies + 1)

    # The auto-created book-return reminder is no longer meaningful once
    # the book is back: cancel it (history is preserved) so the runner
    # skips it. Already completed/cancelled events are left untouched.
    for event in db.scalars(
        select(CalendarEvent).where(
            CalendarEvent.loan_id == loan.id,
            CalendarEvent.event_type == EventType.BOOK_RETURN.value,
            CalendarEvent.status == EventStatus.PENDING.value,
        )
    ).all():
        event.status = EventStatus.CANCELLED.value

    db.commit()
    logger.info(
        "Loan %s returned by %s (book %s)", loan.id, actor.username, loan.book_id
    )
    return loan
