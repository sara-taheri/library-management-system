"""Authentication & user schemas.

Note: `RegisterRequest` intentionally has NO role field - clients cannot
self-assign "admin" (extra JSON fields are ignored by Pydantic).
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.utils.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH


class RegisterRequest(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
        description="3-50 chars; letters, digits, underscore, dot, dash; starts alphanumeric.",
    )
    password: str = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        description=f"At least {MIN_PASSWORD_LENGTH} characters.",
    )
    email: EmailStr | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserOut(BaseModel):
    """Public user representation - never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None = None
    role: str
    created_at: datetime


class MessageResponse(BaseModel):
    message: str


class RegisterResponse(MessageResponse):
    user: UserOut


class LoginResponse(MessageResponse):
    user: UserOut
