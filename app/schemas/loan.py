"""Loan schemas (Checkpoint 2: borrowing and returning)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BorrowRequest(BaseModel):
    book_id: int = Field(description="Id of the book to borrow")


class LoanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    book_id: int
    borrowed_at: datetime
    due_at: datetime
    returned_at: datetime | None = None
    status: str = Field(description='"active" or "returned"')
    is_overdue: bool
    book_title: str
    borrower: str


class LoanListResponse(BaseModel):
    items: list[LoanOut]
    total: int
    page: int
    page_size: int
    pages: int
