"""Loan model - replaces the legacy `borrows.json` records.

Key improvements over the legacy borrow records:
- timestamped (borrowed_at / due_at / returned_at),
- returned loans are KEPT (status="returned") so users get a full
  borrowing history instead of losing the record on return,
- foreign keys to users/books guarantee referential integrity
  (no more orphan records like the legacy `sara_admin` row).
"""
import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, utcnow

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.user import User


class LoanStatus(str, enum.Enum):
    ACTIVE = "active"
    RETURNED = "returned"


class Loan(Base):
    __tablename__ = "loans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)

    borrowed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    returned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(
        String(10), default=LoanStatus.ACTIVE.value, index=True
    )

    user: Mapped["User"] = relationship(back_populates="loans")
    book: Mapped["Book"] = relationship(back_populates="loans")

    @property
    def is_overdue(self) -> bool:
        """An active loan past its due date. Derived, never stored,
        so it can never go stale."""
        return self.status == LoanStatus.ACTIVE.value and utcnow() > self.due_at

    # Convenience accessors used by LoanOut and the page templates so
    # callers never have to walk relationships manually.
    @property
    def book_title(self) -> str:
        return self.book.title if self.book is not None else "(removed)"

    @property
    def borrower(self) -> str:
        return self.user.username if self.user is not None else "(unknown)"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Loan {self.id} user={self.user_id} book={self.book_id} {self.status}>"
