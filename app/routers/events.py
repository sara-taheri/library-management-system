"""Calendar events API (Checkpoint 3).

Endpoints:
    GET    /api/events?date=YYYY-MM-DD      events of one day
    GET    /api/events?month=YYYY-MM        events of one month
    GET    /api/events                      all visible events
    POST   /api/events                      create          (signed-in)
    GET    /api/events/{id}                 details         (visibility rules)
    PUT    /api/events/{id}                 update          (owner or admin)
    DELETE /api/events/{id}                 delete          (owner or admin)
    POST   /api/events/{id}/cancel          cancel pending  (owner or admin)

Visibility: announcement/maintenance are public; other events belong to
their creator; admins see everything. Rules live in event_service.
"""
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db, require_user
from app.models import CalendarEvent, User
from app.schemas.event import (
    EventCreate,
    EventListResponse,
    EventMessageResponse,
    EventOut,
    EventUpdate,
)
from app.services import event_service
from app.services.event_service import EventError

router = APIRouter(prefix="/api/events", tags=["events"])


def _raise_event_error(exc: EventError):
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("", response_model=EventListResponse)
def list_events(
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_current_user),
    day: date_type | None = Query(None, alias="date", description="YYYY-MM-DD"),
    month: str | None = Query(
        None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM"
    ),
    event_type: str | None = Query(None, alias="type"),
    event_status: str | None = Query(
        None, alias="status", pattern="^(pending|completed|cancelled)$"
    ),
) -> EventListResponse:
    month_tuple = None
    if month:
        year, month_number = month.split("-")
        month_tuple = (int(year), int(month_number))
    events = event_service.list_events(
        db,
        viewer=viewer,
        day=day,
        month=month_tuple,
        event_type=event_type,
        status=event_status,
    )
    return EventListResponse(
        items=[EventOut.model_validate(event) for event in events],
        total=len(events),
        day=day,
        month=month,
    )


@router.post("", response_model=EventOut, status_code=201)
def create_event(
    payload: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
) -> CalendarEvent:
    try:
        return event_service.create_event(
            db,
            creator=current_user,
            title=payload.title,
            description=payload.description,
            event_date=payload.event_date,
            event_type=payload.event_type,
            book_id=payload.book_id,
            loan_id=payload.loan_id,
        )
    except EventError as exc:
        _raise_event_error(exc)


@router.get("/{event_id}", response_model=EventOut)
def event_detail(
    event_id: int,
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_current_user),
) -> CalendarEvent:
    event = event_service.get_event(db, event_id)
    visible = event is not None and (
        event.is_public or event_service.can_manage(event, viewer)
    )
    if not visible:
        # 404 (not 403) so private events do not leak their existence.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )
    return event


@router.put("/{event_id}", response_model=EventOut)
def update_event(
    event_id: int,
    payload: EventUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
) -> CalendarEvent:
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update. Send at least one field.",
        )
    try:
        return event_service.update_event(
            db, event_id=event_id, actor=current_user, fields=fields
        )
    except EventError as exc:
        _raise_event_error(exc)


@router.delete("/{event_id}", response_model=EventMessageResponse)
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    try:
        message = event_service.delete_event(
            db, event_id=event_id, actor=current_user
        )
    except EventError as exc:
        _raise_event_error(exc)
    return EventMessageResponse(message=message)


@router.post("/{event_id}/cancel", response_model=EventOut)
def cancel_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
) -> CalendarEvent:
    try:
        return event_service.cancel_event(
            db, event_id=event_id, actor=current_user
        )
    except EventError as exc:
        _raise_event_error(exc)
