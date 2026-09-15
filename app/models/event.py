"""CalendarEvent model - the single calendar/scheduling system.

Checkpoint 3 redesigned the Phase-2 placeholder table IN PLACE (no
second calendar system): user_id -> created_by, start_at -> event_date,
end_at/all_day/updated_at dropped, and optional book/loan links plus
the runner fields (status, scheduled_at, executed_at, result_message)
added. `scripts/upgrade_db.py` migrates existing databases.

Two roles in one table, on purpose (simple and explainable):
- calendar entries shown in the monthly UI (all types),
- scheduled tasks the Checkpoint-4 runner executes: any event whose
  type is in TASK_TYPES gets scheduled_at set, so the runner has a
  single query to find due work (status=pending, scheduled_at <= now).
"""
import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, utcnow

if TYPE_CHECKING:
    from app.models.book import Book
    from app.models.loan import Loan
    from app.models.user import User


class EventType(str, enum.Enum):
    GENERAL = "general"            # personal appointment - not a runner task
    REMINDER = "reminder"          # user-scheduled reminder
    BOOK_RETURN = "book_return"    # book return reminder (auto-created on borrow)
    ANNOUNCEMENT = "announcement"  # library-wide announcement (admin only)
    MAINTENANCE = "maintenance"    # maintenance notice (admin only)
    CUSTOM_TASK = "custom_task"    # custom scheduled task


class EventStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


#: Types the calendar runner (Checkpoint 4) processes.
TASK_TYPES = frozenset(
    {
        EventType.REMINDER.value,
        EventType.BOOK_RETURN.value,
        EventType.ANNOUNCEMENT.value,
        EventType.MAINTENANCE.value,
        EventType.CUSTOM_TASK.value,
    }
)

#: Library-wide types: visible to everyone, creatable by admins only.
PUBLIC_TYPES = frozenset({EventType.ANNOUNCEMENT.value, EventType.MAINTENANCE.value})


class CalendarEvent(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    event_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_type: Mapped[str] = mapped_column(
        String(20), default=EventType.GENERAL.value, index=True
    )

    # Optional links: an event may relate to a book and/or a loan
    # (e.g. the auto-created "Return '<title>'" book-return reminder).
    book_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("books.id"), nullable=True
    )
    loan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("loans.id"), nullable=True
    )

    # Runner fields (Checkpoint 4). scheduled_at is set for task types
    # (defaults to event_date); executed_at/result_message are filled in
    # by the runner when it processes a due event.
    status: Mapped[str] = mapped_column(
        String(12), default=EventStatus.PENDING.value, index=True
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    result_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    creator: Mapped["User"] = relationship(back_populates="created_events")
    book: Mapped[Optional["Book"]] = relationship()
    loan: Mapped[Optional["Loan"]] = relationship()

    # ------------------------------------------------------ derived helpers

    @property
    def creator_name(self) -> str:
        return self.creator.username if self.creator is not None else "(unknown)"

    @property
    def is_task(self) -> bool:
        """True when the calendar runner should process this event."""
        return self.event_type in TASK_TYPES

    @property
    def is_public(self) -> bool:
        """Library-wide events are visible to every visitor."""
        return self.event_type in PUBLIC_TYPES

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CalendarEvent {self.id} {self.title!r} date={self.event_date} {self.status}>"
