"""Pydantic schemas (request/response validation) for the HTTP API."""
from app.schemas.admin import AdminOverview
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MessageResponse,
    RegisterRequest,
    RegisterResponse,
    UserOut,
)
from app.schemas.book import BookListResponse, BookOut
from app.schemas.loan import BorrowRequest, LoanListResponse, LoanOut

__all__ = [
    "AdminOverview",
    "BookListResponse",
    "BookOut",
    "BorrowRequest",
    "LoanListResponse",
    "LoanOut",
    "LoginRequest",
    "LoginResponse",
    "MessageResponse",
    "RegisterRequest",
    "RegisterResponse",
    "UserOut",
]
