"""Authentication API (JSON).

Endpoints:
    POST /api/auth/register  create an account (always role=member)
    POST /api/auth/login     verify credentials + start session
    POST /api/auth/logout    end session
    GET  /api/auth/me        current user (401 when unauthenticated)

The server-rendered pages (app/routers/pages.py) call the same service
layer, so behavior can never drift between UI and API.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.deps import get_db, require_user
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MessageResponse,
    RegisterRequest,
    RegisterResponse,
    UserOut,
)
from app.services import auth_service
from app.services.auth_service import AuthError
from app.utils.sessions import login_session, logout_session

router = APIRouter(prefix="/api/auth", tags=["auth"])

INVALID_CREDENTIALS_DETAIL = "Invalid username or password."


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    try:
        user = auth_service.register_user(
            db,
            username=payload.username,
            password=payload.password,
            email=payload.email,
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return RegisterResponse(
        message="Account created successfully. You can now log in.",
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = auth_service.authenticate(
        db, username=payload.username, password=payload.password
    )
    if user is None:
        # Generic message: never reveal whether the username exists.
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS_DETAIL)
    login_session(request, user)
    return LoginResponse(
        message=f"Welcome back, {user.username}!", user=UserOut.model_validate(user)
    )


@router.post("/logout", response_model=MessageResponse)
def logout(request: Request):
    logout_session(request)
    return MessageResponse(message="You have been logged out.")


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(require_user)):
    return current_user
