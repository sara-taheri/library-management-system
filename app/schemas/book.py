"""Book schemas.

Read schemas existed since Phase 2; Checkpoint 1 adds the admin
create/update/delete contracts.
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
    is_active: bool = True
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


class BookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    author: str = Field(min_length=1, max_length=255)
    isbn: str | None = Field(None, max_length=20)
    genre: str | None = Field(None, max_length=100)
    description: str | None = None
    total_copies: int = Field(1, ge=1, le=100000)


class BookUpdate(BaseModel):
    """Partial update: only the fields present in the request are applied."""

    title: str | None = Field(None, min_length=1, max_length=255)
    author: str | None = Field(None, min_length=1, max_length=255)
    isbn: str | None = Field(None, max_length=20)
    genre: str | None = Field(None, max_length=100)
    description: str | None = None
    total_copies: int | None = Field(None, ge=0, le=100000)
    is_active: bool | None = None


class BookDeleteResponse(BaseModel):
    message: str
    deleted: bool = Field(description="true = permanently deleted, false = deactivated")
    book: BookOut | None = None
