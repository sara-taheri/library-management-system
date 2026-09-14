"""Book schemas.

Phase 2 exposes read-only output schemas; create/update schemas arrive
with the admin CRUD endpoints in Phase 4.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field


class BookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    author: str
    isbn: str | None = None
    genre: str | None = None
    description: str | None = None
    total_copies: int
    available_copies: int
    created_at: datetime

    @computed_field
    @property
    def is_available(self) -> bool:
        return self.available_copies > 0


class BookListResponse(BaseModel):
    items: list[BookOut]
    total: int = Field(description="Total number of books matching the filters")
    page: int
    page_size: int
    pages: int
