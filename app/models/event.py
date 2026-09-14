"""CalendarEvent model - the scheduling feature (UI lands in Phase 7).

Events belong to a user and may optionally be linked to a loan (e.g. an
auto-created "Book due" event, or a return reminder the user schedules
for a specific date/time).
"""
import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, utcnow

if TYPE_CHECKING:
    from app.models.loan import Loan
    from app.models.user import User


class EventType(str, enum.Enum):
    GENERAL = "general"        # user-created personal event
    DUE_DATE = "due_date"      # auto-created when a book is borrowed
    REMINDER = "reminder"      # user-scheduled reminder (e.g. "return book")
    LIBRARY = "library"        # library-wide activity/announcement


class CalendarEvent(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)

    event_type: Mapped[str] = mapped_column(
        String(20), default=EventType.GENERAL.value, index=True
    )
    loan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("loans.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship(back_populates="events")
    loan: Mapped[Optional["Loan"]] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CalendarEvent {self.id} {self.title!r} start={self.start_at}>"
