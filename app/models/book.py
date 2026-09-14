"""Book model (evolves the legacy `model.Book`).

The single legacy `stock` counter is split into `total_copies` (what the
library owns) and `available_copies` (what can be borrowed right now),
which is what proper availability tracking requires.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, utcnow

if TYPE_CHECKING:
    from app.models.loan import Loan


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    author: Mapped[str] = mapped_column(String(255), index=True)
    isbn: Mapped[Optional[str]] = mapped_column(String(20), unique=True, nullable=True)
    genre: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    total_copies: Mapped[int] = mapped_column(default=1)
    available_copies: Mapped[int] = mapped_column(default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    loans: Mapped[list["Loan"]] = relationship(back_populates="book")

    @property
    def is_available(self) -> bool:
        return self.available_copies > 0

    @property
    def stock(self) -> int:
        """Backwards-compatible alias for the legacy `stock` field."""
        return self.available_copies

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Book {self.id} {self.title!r} avail={self.available_copies}/{self.total_copies}>"
