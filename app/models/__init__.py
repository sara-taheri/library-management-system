"""ORM models.

Evolves the legacy `model.py` (Book, User) into a relational schema and
adds the entities the web application needs: Loan (with due dates and
history) and CalendarEvent (scheduling feature, wired up in Phase 7).
"""
from app.models.book import Book
from app.models.event import CalendarEvent, EventType
from app.models.loan import Loan, LoanStatus
from app.models.user import User

__all__ = ["Book", "CalendarEvent", "EventType", "Loan", "LoanStatus", "User"]
