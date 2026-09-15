"""ORM models.

Evolves the legacy `model.py` (Book, User) into a relational schema and
adds the entities the web application needs: Loan (with due dates and
history) and CalendarEvent (scheduling feature, wired up in Phase 7).
"""
from app.models.book import Book
from app.models.event import (
    PUBLIC_TYPES,
    TASK_TYPES,
    CalendarEvent,
    EventStatus,
    EventType,
)
from app.models.loan import Loan, LoanStatus
from app.models.user import User

__all__ = [
    "Book",
    "CalendarEvent",
    "EventStatus",
    "EventType",
    "Loan",
    "LoanStatus",
    "PUBLIC_TYPES",
    "TASK_TYPES",
    "User",
]
