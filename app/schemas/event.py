"""Calendar event schemas (Checkpoint 3)."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    event_date: datetime
    event_type: str = Field(
        "general",
        description="general | reminder | book_return | announcement | "
        "maintenance | custom_task",
    )
    book_id: int | None = None
    loan_id: int | None = None


class EventUpdate(BaseModel):
    """Partial update: only the fields present in the request are applied."""

    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    event_date: datetime | None = None
    event_type: str | None = None
    book_id: int | None = None
    loan_id: int | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by: int
    title: str
    description: str | None = None
    event_date: datetime
    event_type: str
    book_id: int | None = None
    loan_id: int | None = None
    status: str
    scheduled_at: datetime | None = None
    executed_at: datetime | None = None
    result_message: str | None = None
    created_at: datetime
    creator_name: str
    is_task: bool
    is_public: bool


class EventListResponse(BaseModel):
    items: list[EventOut]
    total: int = Field(description="Number of events returned")
    day: date | None = Field(None, description="Echo of the ?date= filter")
    month: str | None = Field(None, description="Echo of the ?month= filter")


class EventMessageResponse(BaseModel):
    message: str
