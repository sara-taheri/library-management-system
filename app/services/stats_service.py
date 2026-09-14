"""Library statistics (shared by the admin API and admin page).

Phase 3 reports simple counts; Phase 5-6 extend this with borrowing
analytics (most-borrowed books, overdue rates, activity per member).
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Book, CalendarEvent, Loan, LoanStatus, User


def library_overview(db: Session) -> dict:
    def count(model) -> int:
        return db.scalar(select(func.count()).select_from(model)) or 0

    return {
        "users": count(User),
        "books": count(Book),
        "loans_total": count(Loan),
        "loans_active": db.scalar(
            select(func.count())
            .select_from(Loan)
            .where(Loan.status == LoanStatus.ACTIVE.value)
        )
        or 0,
        "events": count(CalendarEvent),
    }
