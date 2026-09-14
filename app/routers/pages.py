"""Server-rendered pages (Phase 3: home, authentication, account, admin).

Conventions:
- Route handlers contain NO business logic - they call the same services
  as the JSON API.
- Forms use the Post/Redirect/Get pattern with flash messages.
- Every form carries a CSRF token (app.utils.csrf).
- Unauthenticated access to protected pages redirects to
  /login?next=<original path>; `next` is validated to block
  open redirects.
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from app.deps import get_current_user, get_db
from app.models import Book, User
from app.services import auth_service
from app.services.auth_service import AuthError
from app.services.stats_service import library_overview
from app.utils.csrf import csrf_token_is_valid
from app.utils.flash import flash
from app.utils.sessions import login_session, logout_session
from app.utils.urls import safe_redirect_target
from app.web import render

router = APIRouter(tags=["pages"])

DEFAULT_NEXT = "/account"


def _redirect_to_login(request: Request) -> RedirectResponse:
    return RedirectResponse(
        f"/login?next={quote(request.url.path)}", status_code=303
    )


@router.get("/")
def home(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    book_count = db.scalar(select(func.count()).select_from(Book)) or 0
    return render(
        request, "home.html", current_user=current_user, book_count=book_count
    )


# ---------------------------------------------------------------- login


@router.get("/login")
def login_page(
    request: Request,
    next_url: str = Query("", alias="next"),
    current_user: User | None = Depends(get_current_user),
):
    if current_user is not None:
        return RedirectResponse(DEFAULT_NEXT, status_code=303)
    return render(
        request,
        "login.html",
        next=next_url or DEFAULT_NEXT,
        form_username="",
        form_error=None,
    )


@router.post("/login")
def login_submit(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
    username: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form("", alias="_csrf"),
    next_url: str = Form(DEFAULT_NEXT, alias="next"),
):
    if current_user is not None:
        return RedirectResponse(DEFAULT_NEXT, status_code=303)

    if not csrf_token_is_valid(request, csrf_token):
        flash(request, "Your session expired. Please try again.", "error")
        return RedirectResponse("/login", status_code=303)

    user = auth_service.authenticate(db, username=username, password=password)
    if user is None:
        # Re-render with the error (keeps the typed username).
        return render(
            request,
            "login.html",
            next=next_url,
            form_username=username,
            form_error="Invalid username or password.",
        )

    login_session(request, user)
    flash(request, f"Welcome back, {user.username}!", "success")
    return RedirectResponse(
        safe_redirect_target(next_url, DEFAULT_NEXT), status_code=303
    )


# ------------------------------------------------------------- register


@router.get("/register")
def register_page(
    request: Request,
    current_user: User | None = Depends(get_current_user),
):
    if current_user is not None:
        return RedirectResponse(DEFAULT_NEXT, status_code=303)
    return render(request, "register.html", form={}, form_error=None)


@router.post("/register")
def register_submit(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
    username: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    confirm_password: str = Form(""),
    csrf_token: str = Form("", alias="_csrf"),
):
    if current_user is not None:
        return RedirectResponse(DEFAULT_NEXT, status_code=303)

    if not csrf_token_is_valid(request, csrf_token):
        flash(request, "Your session expired. Please try again.", "error")
        return RedirectResponse("/register", status_code=303)

    form = {"username": username.strip(), "email": email.strip()}

    if password != confirm_password:
        return render(
            request, "register.html", form=form, form_error="Passwords do not match."
        )

    try:
        user = auth_service.register_user(
            db, username=username, password=password, email=email
        )
    except AuthError as exc:
        return render(request, "register.html", form=form, form_error=exc.message)

    # Auto-login after registration for a frictionless signup flow.
    login_session(request, user)
    flash(request, f"Welcome, {user.username}! Your account is ready.", "success")
    return RedirectResponse(DEFAULT_NEXT, status_code=303)


# --------------------------------------------------------------- logout


@router.post("/logout")
def logout_submit(
    request: Request,
    csrf_token: str = Form("", alias="_csrf"),
):
    if not csrf_token_is_valid(request, csrf_token):
        flash(request, "Could not log you out (invalid form token).", "error")
        return RedirectResponse("/", status_code=303)
    logout_session(request)
    flash(request, "You have been logged out.", "info")
    return RedirectResponse("/", status_code=303)


# -------------------------------------------------------------- account


@router.get("/account")
def account_page(
    request: Request,
    current_user: User | None = Depends(get_current_user),
):
    if current_user is None:
        return _redirect_to_login(request)
    return render(request, "account.html", current_user=current_user)


# ---------------------------------------------------------------- admin


@router.get("/admin")
def admin_page(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user is None:
        return _redirect_to_login(request)
    if not current_user.is_admin:
        flash(request, "Access denied. Admins only.", "error")
        return RedirectResponse(DEFAULT_NEXT, status_code=303)
    return render(
        request,
        "admin.html",
        current_user=current_user,
        stats=library_overview(db),
    )
