"""Calendar task runner (Checkpoint 4).

A deliberately tiny piece of infrastructure - no Celery, no Redis, no
background threads. One function processes every due pending event and
is driven by ``scripts/run_calendar_tasks.py`` (manually or from cron).

Safety rules:
- only events with status == "pending", a scheduled_at value, and
  scheduled_at <= now are processed; completed and cancelled events are
  never touched, and non-task types (e.g. "general") have no
  scheduled_at at all;
- success: status -> "completed", executed_at + result_message stored;
- failure: the event STAYS PENDING so the next run retries it; the
  attempt is recorded (executed_at + "ERROR: ..." result_message) and
  never crashes the run;
- duplicate execution is prevented by the pending-status filter plus a
  single transaction per run: once an event is completed, later runs
  cannot pick it up again;
- processors are injectable, which keeps failure handling testable
  without external services.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models import CalendarEvent, EventStatus, EventType, LoanStatus

logger = logging.getLogger("app.runner")


# --------------------------------------------------------------- processors
#
# A processor takes the event and returns a short human-readable result
# message. Raising any exception means "this task failed - keep it
# pending and retry later". The defaults have no external side effects
# (no mail server here); the durable effect is the event row itself:
# completed, timestamped, with the message recorded.


def process_reminder(event: CalendarEvent) -> str:
    return f"Reminder delivered to {event.creator_name}: {event.title}"


def process_book_return(event: CalendarEvent) -> str:
    loan = event.loan
    if loan is None:
        return "Book return reminder recorded (no linked loan; nothing to send)."
    if loan.status != LoanStatus.ACTIVE.value:
        returned_on = f"{loan.returned_at:%Y-%m-%d}" if loan.returned_at else "?"
        return f"Loan #{loan.id} was already returned ({returned_on}); no reminder sent."
    if loan.is_overdue:
        return (
            f"OVERDUE notice sent to {loan.borrower}: '{loan.book_title}' "
            f"was due {loan.due_at:%Y-%m-%d}."
        )
    return (
        f"Return reminder sent to {loan.borrower}: '{loan.book_title}' "
        f"is due {loan.due_at:%Y-%m-%d}."
    )


def process_announcement(event: CalendarEvent) -> str:
    return f"Library announcement published: {event.title}"


def process_maintenance(event: CalendarEvent) -> str:
    return f"Maintenance notice posted: {event.title}"


def process_custom_task(event: CalendarEvent) -> str:
    return f"Custom task executed: {event.title}"


DEFAULT_PROCESSORS = {
    EventType.REMINDER.value: process_reminder,
    EventType.BOOK_RETURN.value: process_book_return,
    EventType.ANNOUNCEMENT.value: process_announcement,
    EventType.MAINTENANCE.value: process_maintenance,
    EventType.CUSTOM_TASK.value: process_custom_task,
}


# ------------------------------------------------------------------- runner


def find_due_events(
    db: Session, now=None, processors: dict | None = None, limit: int = 100
) -> list[CalendarEvent]:
    """Pending task events whose scheduled_at has arrived, oldest first."""
    now = now or utcnow()
    processors = DEFAULT_PROCESSORS if processors is None else processors
    statement = (
        select(CalendarEvent)
        .where(
            CalendarEvent.status == EventStatus.PENDING.value,
            CalendarEvent.scheduled_at.isnot(None),
            CalendarEvent.scheduled_at <= now,
            CalendarEvent.event_type.in_(list(processors)),
        )
        .order_by(CalendarEvent.scheduled_at, CalendarEvent.id)
        .limit(limit)
    )
    return list(db.scalars(statement).all())


def run_due_tasks(
    db: Session, now=None, processors: dict | None = None, limit: int = 100
) -> dict:
    """Process every due pending event once; return a printable summary.

    The whole run is a single transaction: statuses, execution times and
    result messages are committed together, which (together with the
    pending-only filter) prevents duplicate execution across runs.
    """
    now = now or utcnow()
    processors = DEFAULT_PROCESSORS if processors is None else processors
    due_events = find_due_events(db, now=now, processors=processors, limit=limit)

    results = []
    succeeded = failed = 0
    for event in due_events:
        processor = processors[event.event_type]
        try:
            message = processor(event)
        except Exception as exc:  # noqa: BLE001 - a runner must never crash
            failed += 1
            # Stay pending so the next run retries; record the attempt.
            event.executed_at = now
            event.result_message = f"ERROR: {exc}"
            logger.warning(
                "Task %s (%s, '%s') failed: %s",
                event.id, event.event_type, event.title, exc,
            )
            results.append(_result_row(event))
            continue

        succeeded += 1
        event.status = EventStatus.COMPLETED.value
        event.executed_at = now
        event.result_message = message
        logger.info(
            "Task %s (%s, '%s') completed: %s",
            event.id, event.event_type, event.title, message,
        )
        results.append(_result_row(event))

    db.commit()
    return {
        "now": f"{now:%Y-%m-%d %H:%M:%S}",
        "due": len(due_events),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


def _result_row(event: CalendarEvent) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "event_type": event.event_type,
        "status": event.status,
        "result_message": event.result_message,
    }
