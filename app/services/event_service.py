"""Calendar event business logic (Checkpoint 3).

One calendar system, built on the existing CalendarEvent model.

Visibility / authorization rules (enforced here, used by API + pages):
- library-wide events (announcement, maintenance) are visible to
  everyone, including guests, but only admins may create/edit them;
- every other event is visible to its creator;
- admins see and manage ALL events.

Task scheduling: events whose type is in TASK_TYPES get scheduled_at
(default = event_date) and are picked up by the Checkpoint-4 runner
while status == "pending".
"""
import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models import (
    TASK_TYPES,
    Book,
    CalendarEvent,
    EventStatus,
    EventType,
    Loan,
    User,
)

logger = logging.getLogger("app.events")

PUBLIC_TYPE_LIST = ("announcement", "maintenance")  # == models.PUBLIC_TYPES
ALL_TYPE_VALUES = [member.value for member in EventType]

#: Human-friendly labels shared by the API docs and the HTML forms.
TYPE_LABELS = {
    EventType.GENERAL.value: "Personal event",
    EventType.REMINDER.value: "Reminder",
    EventType.BOOK_RETURN.value: "Book return reminder",
    EventType.ANNOUNCEMENT.value: "Library announcement",
    EventType.MAINTENANCE.value: "Maintenance notice",
    EventType.CUSTOM_TASK.value: "Custom task",
}


def type_choices_for(user: User) -> list[tuple[str, str]]:
    """(value, label) event types this user may create in the web form."""
    return [
        (value, TYPE_LABELS[value])
        for value in ALL_TYPE_VALUES
        if value not in PUBLIC_TYPE_LIST or user.is_admin
    ]


class EventError(Exception):
    """User-facing calendar error (status_code maps to HTTP)."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ------------------------------------------------------------- visibility


def _visibility_filter(viewer: User | None):
    """SQL condition limiting rows to what `viewer` may see."""
    public = CalendarEvent.event_type.in_(PUBLIC_TYPE_LIST)
    if viewer is None:
        return public
    if viewer.is_admin:
        return true()
    return or_(public, CalendarEvent.created_by == viewer.id)


def can_manage(event: CalendarEvent, actor: User | None) -> bool:
    if actor is None:
        return False
    return actor.is_admin or event.created_by == actor.id


# ------------------------------------------------------------------ reads


def get_event(db: Session, event_id: int) -> CalendarEvent | None:
    return db.get(CalendarEvent, event_id)


def list_events(
    db: Session,
    *,
    viewer: User | None,
    day: date | None = None,
    month: tuple[int, int] | None = None,
    event_type: str | None = None,
    status: str | None = None,
    limit: int = 500,
) -> list[CalendarEvent]:
    """Visible events for one day and/or one month, chronological."""
    stmt = select(CalendarEvent).where(_visibility_filter(viewer))
    if day is not None:
        start = datetime.combine(day, time.min)
        stmt = stmt.where(
            CalendarEvent.event_date >= start,
            CalendarEvent.event_date < start + timedelta(days=1),
        )
    if month is not None:
        year, month_number = month
        start = datetime(year, month_number, 1)
        end = datetime(year + (month_number == 12), month_number % 12 + 1, 1)
        stmt = stmt.where(CalendarEvent.event_date >= start, CalendarEvent.event_date < end)
    if event_type:
        stmt = stmt.where(CalendarEvent.event_type == event_type)
    if status:
        stmt = stmt.where(CalendarEvent.status == status)
    return list(
        db.scalars(
            stmt.order_by(CalendarEvent.event_date, CalendarEvent.id).limit(limit)
        ).all()
    )


def upcoming_events(db: Session, *, viewer: User | None, limit: int = 5, now=None):
    """The viewer's next visible events (dashboard widget)."""
    now = now or utcnow()
    stmt = (
        select(CalendarEvent)
        .where(_visibility_filter(viewer), CalendarEvent.event_date >= now)
        .order_by(CalendarEvent.event_date, CalendarEvent.id)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


# ----------------------------------------------------------------- writes


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time(9, 0))
    raise EventError("event_date must be a date or datetime.")


def _check_links(db: Session, actor: User, book_id, loan_id) -> None:
    if book_id is not None and db.get(Book, book_id) is None:
        raise EventError("Linked book not found.", status_code=404)
    if loan_id is not None:
        loan = db.get(Loan, loan_id)
        if loan is None:
            raise EventError("Linked loan not found.", status_code=404)
        if not (actor.is_admin or loan.user_id == actor.id):
            raise EventError("You can only link your own loans.", status_code=403)


def create_event(
    db: Session,
    *,
    creator: User,
    title: str,
    event_date,
    event_type: str = EventType.GENERAL.value,
    description: str | None = None,
    book_id: int | None = None,
    loan_id: int | None = None,
) -> CalendarEvent:
    title = (title or "").strip()
    if not title:
        raise EventError("Title is required.")
    if len(title) > 200:
        raise EventError("Title must be 200 characters or fewer.")
    if event_type not in ALL_TYPE_VALUES:
        raise EventError(
            f"Unknown event type '{event_type}'. "
            f"Choose one of: {', '.join(ALL_TYPE_VALUES)}."
        )
    if event_type in PUBLIC_TYPE_LIST and not creator.is_admin:
        raise EventError(
            f"Only admins can create '{event_type}' events.", status_code=403
        )
    when = _as_datetime(event_date)
    _check_links(db, creator, book_id, loan_id)

    event = CalendarEvent(
        created_by=creator.id,
        title=title,
        description=(description or "").strip() or None,
        event_date=when,
        event_type=event_type,
        book_id=book_id,
        loan_id=loan_id,
        status=EventStatus.PENDING.value,
        # Task-like events are scheduled for their event date so the
        # runner can find due work with one indexed query.
        scheduled_at=when if event_type in TASK_TYPES else None,
    )
    db.add(event)
    db.commit()
    logger.info(
        "User %s created %s event %s (%s)",
        creator.username, event_type, event.id, when,
    )
    return event


def update_event(db: Session, *, event_id: int, actor: User, fields: dict) -> CalendarEvent:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise EventError("Event not found.", status_code=404)
    if not can_manage(event, actor):
        raise EventError("You can only manage your own events.", status_code=403)

    fields = dict(fields)  # never mutate the caller's dict
    if "title" in fields:
        title = (fields["title"] or "").strip()
        if not title:
            raise EventError("Title cannot be empty.")
        if len(title) > 200:
            raise EventError("Title must be 200 characters or fewer.")
        fields["title"] = title
    if "description" in fields:
        fields["description"] = (fields["description"] or "").strip() or None

    new_type = fields.get("event_type", event.event_type)
    if "event_type" in fields:
        if new_type not in ALL_TYPE_VALUES:
            raise EventError(f"Unknown event type '{new_type}'.")
        if new_type in PUBLIC_TYPE_LIST and not actor.is_admin:
            raise EventError(
                f"Only admins can manage '{new_type}' events.", status_code=403
            )
    if event.event_type in PUBLIC_TYPE_LIST and not actor.is_admin:
        # Defensive: admins-only events stay admins-only even if the type
        # is not being changed (a member somehow editing an announcement).
        raise EventError("Only admins can manage library-wide events.", status_code=403)

    if "event_date" in fields and fields["event_date"] is not None:
        fields["event_date"] = _as_datetime(fields["event_date"])

    # Book/loan links: explicit null clears, a value re-validates.
    if "book_id" in fields or "loan_id" in fields:
        _check_links(
            db,
            actor,
            fields.get("book_id", event.book_id),
            fields.get("loan_id", event.loan_id),
        )

    for name in ("title", "description", "event_date", "event_type", "book_id", "loan_id"):
        if name in fields:
            setattr(event, name, fields[name])

    # Keep the runner schedule in sync with date/type changes.
    event.scheduled_at = (
        event.event_date if event.event_type in TASK_TYPES else None
    )

    db.commit()
    logger.info("Event %s updated by %s", event.id, actor.username)
    return event


def delete_event(db: Session, *, event_id: int, actor: User) -> str:
    """Permanently delete an event; returns a human-readable message."""
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise EventError("Event not found.", status_code=404)
    if not can_manage(event, actor):
        raise EventError("You can only manage your own events.", status_code=403)
    title = event.title
    db.delete(event)
    db.commit()
    logger.info("Event %s (%s) deleted by %s", event_id, title, actor.username)
    return f"Event '{title}' was deleted."


def cancel_event(db: Session, *, event_id: int, actor: User) -> CalendarEvent:
    """Cancel a pending event so the runner will skip it."""
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise EventError("Event not found.", status_code=404)
    if not can_manage(event, actor):
        raise EventError("You can only manage your own events.", status_code=403)
    if event.status != EventStatus.PENDING.value:
        raise EventError(
            f"Event is already {event.status}; only pending events can be cancelled.",
            status_code=409,
        )
    event.status = EventStatus.CANCELLED.value
    db.commit()
    logger.info("Event %s cancelled by %s", event.id, actor.username)
    return event
