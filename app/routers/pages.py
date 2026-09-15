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
import calendar as pycalendar
from datetime import date, datetime, time
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from app.config import settings
from app.database import utcnow
from app.deps import get_current_user, get_db
from app.models import Book, LoanStatus, User
from app.services import auth_service, book_service, event_service, loan_service
from app.services.auth_service import AuthError
from app.services.book_service import BookError
from app.services.event_service import EventError
from app.services.loan_service import LoanError
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
    db: Session = Depends(get_db),
):
    if current_user is None:
        return _redirect_to_login(request)
    loans, _total, _pages = loan_service.list_loans(
        db, user_id=current_user.id, page_size=200
    )
    return render(
        request,
        "account.html",
        current_user=current_user,
        loans_active=[l for l in loans if l.status == LoanStatus.ACTIVE.value],
        loans_history=[l for l in loans if l.status == LoanStatus.RETURNED.value],
        upcoming_events=event_service.upcoming_events(db, viewer=current_user),
    )


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


# -------------------------------------------------------------- catalog
#
# Browsing is public; creating/editing/deactivating books is admin-only.
# Deactivation via the web UI is always the safe soft delete - permanent
# deletion stays an explicit API option (DELETE /api/books/{id}?hard=true).


def _admin_denial(request: Request, current_user: User | None, deny_target: str):
    """Return a redirect when the page requires an admin, else None."""
    if current_user is None:
        return _redirect_to_login(request)
    if not current_user.is_admin:
        flash(request, "Access denied. Admins only.", "error")
        return RedirectResponse(deny_target, status_code=303)
    return None


@router.get("/books")
def books_page(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    q: str = Query(""),
    genre: str = Query(""),
    available: str = Query(""),
    all_flag: str = Query("", alias="all"),
):
    is_admin = bool(current_user and current_user.is_admin)
    include_inactive = is_admin and all_flag == "1"
    items, total, _pages = book_service.list_books(
        db,
        q=q or None,
        genre=genre or None,
        available_only=(available == "1"),
        include_inactive=include_inactive,
        page=1,
        page_size=100,
    )
    return render(
        request,
        "books_list.html",
        current_user=current_user,
        books=items,
        total=total,
        q=q,
        genre=genre,
        available=available,
        include_inactive=include_inactive,
    )


# NOTE: /books/new must stay declared BEFORE /books/{book_id}.
@router.get("/books/new")
def book_new_page(
    request: Request,
    current_user: User | None = Depends(get_current_user),
):
    denial = _admin_denial(request, current_user, "/books")
    if denial is not None:
        return denial
    return render(
        request,
        "book_form.html",
        current_user=current_user,
        book=None,
        form={"total_copies": "1"},
        form_error=None,
        action="/books/new",
        submit_label="Add book",
    )


@router.post("/books/new")
def book_new_submit(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
    title: str = Form(""),
    author: str = Form(""),
    isbn: str = Form(""),
    genre: str = Form(""),
    description: str = Form(""),
    total_copies: str = Form("1"),
    csrf_token: str = Form("", alias="_csrf"),
):
    denial = _admin_denial(request, current_user, "/books")
    if denial is not None:
        return denial
    if not csrf_token_is_valid(request, csrf_token):
        flash(request, "Your session expired. Please try again.", "error")
        return RedirectResponse("/books/new", status_code=303)

    form = {
        "title": title.strip(),
        "author": author.strip(),
        "isbn": isbn.strip(),
        "genre": genre.strip(),
        "description": description.strip(),
        "total_copies": total_copies.strip(),
    }

    def _redraw(error: str):
        return render(
            request,
            "book_form.html",
            current_user=current_user,
            book=None,
            form=form,
            form_error=error,
            action="/books/new",
            submit_label="Add book",
        )

    try:
        copies = int(form["total_copies"] or "1")
    except ValueError:
        return _redraw("Total copies must be a whole number.")
    try:
        book = book_service.create_book(
            db,
            title=form["title"],
            author=form["author"],
            isbn=form["isbn"] or None,
            genre=form["genre"] or None,
            description=form["description"] or None,
            total_copies=copies,
        )
    except BookError as exc:
        return _redraw(exc.message)

    flash(request, f"'{book.title}' was added to the catalog.", "success")
    return RedirectResponse(f"/books/{book.id}", status_code=303)


@router.get("/books/{book_id}")
def book_detail_page(
    request: Request,
    book_id: int,
    current_user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    book = book_service.get_book(db, book_id)
    is_admin = bool(current_user and current_user.is_admin)
    if book is None or (not book.is_active and not is_admin):
        raise HTTPException(status_code=404, detail="Book not found")
    active_loan = None
    if current_user is not None:
        active_loan = loan_service.active_loan_for(db, current_user.id, book.id)
    return render(
        request,
        "book_detail.html",
        current_user=current_user,
        book=book,
        active_loan=active_loan,
        loan_period_days=settings.loan_period_days,
    )


@router.get("/books/{book_id}/edit")
def book_edit_page(
    request: Request,
    book_id: int,
    current_user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    denial = _admin_denial(request, current_user, f"/books/{book_id}")
    if denial is not None:
        return denial
    book = book_service.get_book(db, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    form = {
        "title": book.title,
        "author": book.author,
        "isbn": book.isbn or "",
        "genre": book.genre or "",
        "description": book.description or "",
        "total_copies": str(book.total_copies),
        "is_active": book.is_active,
    }
    return render(
        request,
        "book_form.html",
        current_user=current_user,
        book=book,
        form=form,
        form_error=None,
        action=f"/books/{book.id}/edit",
        submit_label="Save changes",
    )


@router.post("/books/{book_id}/edit")
def book_edit_submit(
    request: Request,
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
    title: str = Form(""),
    author: str = Form(""),
    isbn: str = Form(""),
    genre: str = Form(""),
    description: str = Form(""),
    total_copies: str = Form("1"),
    is_active: str = Form(""),
    csrf_token: str = Form("", alias="_csrf"),
):
    denial = _admin_denial(request, current_user, f"/books/{book_id}")
    if denial is not None:
        return denial
    if not csrf_token_is_valid(request, csrf_token):
        flash(request, "Your session expired. Please try again.", "error")
        return RedirectResponse(f"/books/{book_id}/edit", status_code=303)
    book = book_service.get_book(db, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    form = {
        "title": title.strip(),
        "author": author.strip(),
        "isbn": isbn.strip(),
        "genre": genre.strip(),
        "description": description.strip(),
        "total_copies": total_copies.strip(),
        "is_active": is_active == "on",
    }

    def _redraw(error: str):
        return render(
            request,
            "book_form.html",
            current_user=current_user,
            book=book,
            form=form,
            form_error=error,
            action=f"/books/{book.id}/edit",
            submit_label="Save changes",
        )

    try:
        copies = int(form["total_copies"])
    except ValueError:
        return _redraw("Total copies must be a whole number.")
    try:
        book_service.update_book(
            db,
            book.id,
            {
                "title": form["title"],
                "author": form["author"],
                "isbn": form["isbn"] or None,
                "genre": form["genre"] or None,
                "description": form["description"] or None,
                "total_copies": copies,
                "is_active": form["is_active"],
            },
        )
    except BookError as exc:
        return _redraw(exc.message)

    flash(request, f"'{book.title}' was updated.", "success")
    return RedirectResponse(f"/books/{book.id}", status_code=303)


@router.post("/books/{book_id}/delete")
def book_delete_submit(
    request: Request,
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
    csrf_token: str = Form("", alias="_csrf"),
):
    denial = _admin_denial(request, current_user, "/books")
    if denial is not None:
        return denial
    if not csrf_token_is_valid(request, csrf_token):
        flash(request, "Your session expired. Please try again.", "error")
        return RedirectResponse("/books", status_code=303)
    try:
        result = book_service.delete_book(db, book_id, hard=False)
    except BookError as exc:
        flash(request, exc.message, "error")
        return RedirectResponse("/books", status_code=303)
    flash(request, result["message"], "success")
    return RedirectResponse("/books", status_code=303)


# ------------------------------------------------------------ borrowing


@router.post("/books/{book_id}/borrow")
def book_borrow_submit(
    request: Request,
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
    csrf_token: str = Form("", alias="_csrf"),
):
    if current_user is None:
        return _redirect_to_login(request)
    target = f"/books/{book_id}"
    if not csrf_token_is_valid(request, csrf_token):
        flash(request, "Your session expired. Please try again.", "error")
        return RedirectResponse(target, status_code=303)
    try:
        loan = loan_service.borrow_book(db, user=current_user, book_id=book_id)
    except LoanError as exc:
        flash(request, exc.message, "error")
        return RedirectResponse(target, status_code=303)
    flash(
        request,
        f"Borrowed '{loan.book_title}' - due {loan.due_at:%Y-%m-%d}. "
        "A due-date reminder was added to the calendar.",
        "success",
    )
    return RedirectResponse(target, status_code=303)


@router.post("/loans/{loan_id}/return")
def loan_return_submit(
    request: Request,
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
    csrf_token: str = Form("", alias="_csrf"),
    next_url: str = Form("/account", alias="next"),
):
    """Shared return endpoint for the account, book-detail and admin pages."""
    if current_user is None:
        return _redirect_to_login(request)
    target = safe_redirect_target(next_url, DEFAULT_NEXT)
    if not csrf_token_is_valid(request, csrf_token):
        flash(request, "Your session expired. Please try again.", "error")
        return RedirectResponse(target, status_code=303)
    try:
        loan = loan_service.return_book(db, loan_id=loan_id, actor=current_user)
    except LoanError as exc:
        flash(request, exc.message, "error")
        return RedirectResponse(target, status_code=303)
    flash(request, f"Returned '{loan.book_title}'. Thank you!", "success")
    return RedirectResponse(target, status_code=303)


# --------------------------------------------------------- admin: loans


@router.get("/admin/loans")
def admin_loans_page(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    status_filter: str = Query("", alias="status"),
):
    denial = _admin_denial(request, current_user, "/admin")
    if denial is not None:
        return denial
    if status_filter not in ("", "active", "returned"):
        status_filter = ""
    loans, total, _pages = loan_service.list_loans(
        db, status=status_filter or None, page_size=200
    )
    return render(
        request,
        "admin_loans.html",
        current_user=current_user,
        loans=loans,
        total=total,
        status_filter=status_filter,
    )


# ------------------------------------------------------------- calendar
#
# One shared calendar (event_service): the monthly grid is public -
# guests see library-wide announcements/maintenance - while creating
# and managing events requires a login (admins manage everything).


def _parse_month(month: str, fallback: date) -> tuple[int, int]:
    try:
        year, number = month.split("-")
        year, number = int(year), int(number)
        if 1 <= number <= 12 and 1 <= year <= 9999:
            return year, number
    except (ValueError, AttributeError):
        pass
    return fallback.year, fallback.month


@router.get("/calendar")
def calendar_page(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    month: str = Query(""),
    day: str = Query("", alias="date"),
):
    today = utcnow().date()

    selected = None
    if day:
        try:
            selected = date.fromisoformat(day)
        except ValueError:
            selected = None

    if month:
        year, month_number = _parse_month(month, selected or today)
    elif selected is not None:
        year, month_number = selected.year, selected.month
    else:
        year, month_number = today.year, today.month
    if selected is None:
        selected = (
            today
            if (today.year, today.month) == (year, month_number)
            else date(year, month_number, 1)
        )

    month_events = event_service.list_events(
        db, viewer=current_user, month=(year, month_number)
    )
    day_events = event_service.list_events(db, viewer=current_user, day=selected)
    events_by_day: dict = {}
    for event in month_events:
        events_by_day.setdefault(event.event_date.date(), []).append(event)

    weeks = pycalendar.Calendar(firstweekday=0).monthdatescalendar(year, month_number)
    prev_year, prev_number = (year - 1, 12) if month_number == 1 else (year, month_number - 1)
    next_year, next_number = (year + 1, 1) if month_number == 12 else (year, month_number + 1)

    return render(
        request,
        "calendar.html",
        current_user=current_user,
        year=year,
        month_number=month_number,
        month_name=pycalendar.month_name[month_number],
        weekday_names=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        weeks=weeks,
        today=today,
        selected=selected,
        day_events=day_events,
        events_by_day=events_by_day,
        prev_month=f"{prev_year:04d}-{prev_number:02d}",
        next_month=f"{next_year:04d}-{next_number:02d}",
        type_labels=event_service.TYPE_LABELS,
    )


def _event_form_context(db: Session, current_user: User) -> dict:
    books, _total, _pages = book_service.list_books(db, page_size=200)
    return {
        "type_choices": event_service.type_choices_for(current_user),
        "books": books,
    }


@router.get("/calendar/new")
def event_new_page(
    request: Request,
    current_user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
    day: str = Query("", alias="date"),
):
    if current_user is None:
        return _redirect_to_login(request)
    try:
        prefill = date.fromisoformat(day) if day else utcnow().date()
    except ValueError:
        prefill = utcnow().date()
    form = {
        "title": "",
        "description": "",
        "event_date": prefill.isoformat(),
        "event_time": "09:00",
        "event_type": "general",
        "book_id": "",
        "loan_id": "",
    }
    return render(
        request,
        "event_form.html",
        current_user=current_user,
        event=None,
        form=form,
        form_error=None,
        action="/calendar/new",
        submit_label="Create event",
        back_target=f"/calendar?date={prefill.isoformat()}",
        **_event_form_context(db, current_user),
    )


@router.post("/calendar/new")
def event_new_submit(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
    title: str = Form(""),
    description: str = Form(""),
    event_date: str = Form(""),
    event_time: str = Form("09:00"),
    event_type: str = Form("general"),
    book_id: str = Form(""),
    loan_id: str = Form(""),
    csrf_token: str = Form("", alias="_csrf"),
):
    if current_user is None:
        return _redirect_to_login(request)
    if not csrf_token_is_valid(request, csrf_token):
        flash(request, "Your session expired. Please try again.", "error")
        return RedirectResponse("/calendar", status_code=303)

    form = {
        "title": title.strip(),
        "description": description.strip(),
        "event_date": event_date.strip(),
        "event_time": (event_time or "09:00").strip(),
        "event_type": event_type.strip(),
        "book_id": book_id.strip(),
        "loan_id": loan_id.strip(),
    }

    def _redraw(error: str):
        return render(
            request,
            "event_form.html",
            current_user=current_user,
            event=None,
            form=form,
            form_error=error,
            action="/calendar/new",
            submit_label="Create event",
            back_target="/calendar",
            **_event_form_context(db, current_user),
        )

    when = _combine_date_time(form["event_date"], form["event_time"])
    if when is None:
        return _redraw("Please provide a valid date and time.")
    try:
        book = int(form["book_id"]) if form["book_id"] else None
        loan = int(form["loan_id"]) if form["loan_id"] else None
    except ValueError:
        return _redraw("Book/loan references must be numbers.")

    try:
        event = event_service.create_event(
            db,
            creator=current_user,
            title=form["title"],
            description=form["description"],
            event_date=when,
            event_type=form["event_type"],
            book_id=book,
            loan_id=loan,
        )
    except EventError as exc:
        return _redraw(exc.message)

    flash(request, f"Event '{event.title}' was created.", "success")
    return RedirectResponse(
        f"/calendar?date={event.event_date.date().isoformat()}", status_code=303
    )


def _combine_date_time(date_str: str, time_str: str) -> datetime | None:
    try:
        return datetime.combine(
            date.fromisoformat(date_str), time.fromisoformat(time_str or "09:00")
        )
    except ValueError:
        return None


def _owned_event_or_404(db: Session, event_id: int, current_user: User | None):
    event = event_service.get_event(db, event_id)
    if event is None or not event_service.can_manage(event, current_user):
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("/calendar/{event_id}/edit")
def event_edit_page(
    request: Request,
    event_id: int,
    current_user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user is None:
        return _redirect_to_login(request)
    event = _owned_event_or_404(db, event_id, current_user)
    form = {
        "title": event.title,
        "description": event.description or "",
        "event_date": event.event_date.date().isoformat(),
        "event_time": event.event_date.strftime("%H:%M"),
        "event_type": event.event_type,
        "book_id": str(event.book_id or ""),
        "loan_id": str(event.loan_id or ""),
    }
    return render(
        request,
        "event_form.html",
        current_user=current_user,
        event=event,
        form=form,
        form_error=None,
        action=f"/calendar/{event.id}/edit",
        submit_label="Save changes",
        back_target=f"/calendar?date={event.event_date.date().isoformat()}",
        **_event_form_context(db, current_user),
    )


@router.post("/calendar/{event_id}/edit")
def event_edit_submit(
    request: Request,
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
    title: str = Form(""),
    description: str = Form(""),
    event_date: str = Form(""),
    event_time: str = Form("09:00"),
    event_type: str = Form("general"),
    book_id: str = Form(""),
    loan_id: str = Form(""),
    csrf_token: str = Form("", alias="_csrf"),
):
    if current_user is None:
        return _redirect_to_login(request)
    event = _owned_event_or_404(db, event_id, current_user)
    day_target = f"/calendar?date={event.event_date.date().isoformat()}"
    if not csrf_token_is_valid(request, csrf_token):
        flash(request, "Your session expired. Please try again.", "error")
        return RedirectResponse(day_target, status_code=303)

    form = {
        "title": title.strip(),
        "description": description.strip(),
        "event_date": event_date.strip(),
        "event_time": (event_time or "09:00").strip(),
        "event_type": event_type.strip(),
        "book_id": book_id.strip(),
        "loan_id": loan_id.strip(),
    }

    def _redraw(error: str):
        return render(
            request,
            "event_form.html",
            current_user=current_user,
            event=event,
            form=form,
            form_error=error,
            action=f"/calendar/{event.id}/edit",
            submit_label="Save changes",
            back_target=day_target,
            **_event_form_context(db, current_user),
        )

    when = _combine_date_time(form["event_date"], form["event_time"])
    if when is None:
        return _redraw("Please provide a valid date and time.")
    try:
        book = int(form["book_id"]) if form["book_id"] else None
        loan = int(form["loan_id"]) if form["loan_id"] else None
    except ValueError:
        return _redraw("Book/loan references must be numbers.")

    try:
        event_service.update_event(
            db,
            event_id=event.id,
            actor=current_user,
            fields={
                "title": form["title"],
                "description": form["description"] or None,
                "event_date": when,
                "event_type": form["event_type"],
                "book_id": book,
                "loan_id": loan,
            },
        )
    except EventError as exc:
        return _redraw(exc.message)

    flash(request, f"Event '{form['title']}' was updated.", "success")
    return RedirectResponse(f"/calendar?date={when.date().isoformat()}", status_code=303)


@router.post("/calendar/{event_id}/cancel")
def event_cancel_submit(
    request: Request,
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
    csrf_token: str = Form("", alias="_csrf"),
):
    if current_user is None:
        return _redirect_to_login(request)
    if not csrf_token_is_valid(request, csrf_token):
        flash(request, "Your session expired. Please try again.", "error")
        return RedirectResponse("/calendar", status_code=303)
    try:
        event = event_service.cancel_event(
            db, event_id=event_id, actor=current_user
        )
    except EventError as exc:
        flash(request, exc.message, "error")
        return RedirectResponse("/calendar", status_code=303)
    flash(request, f"Event '{event.title}' was cancelled.", "success")
    return RedirectResponse(
        f"/calendar?date={event.event_date.date().isoformat()}", status_code=303
    )


@router.post("/calendar/{event_id}/delete")
def event_delete_submit(
    request: Request,
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
    csrf_token: str = Form("", alias="_csrf"),
):
    if current_user is None:
        return _redirect_to_login(request)
    if not csrf_token_is_valid(request, csrf_token):
        flash(request, "Your session expired. Please try again.", "error")
        return RedirectResponse("/calendar", status_code=303)
    event = event_service.get_event(db, event_id)
    day_target = (
        f"/calendar?date={event.event_date.date().isoformat()}" if event else "/calendar"
    )
    try:
        message = event_service.delete_event(
            db, event_id=event_id, actor=current_user
        )
    except EventError as exc:
        flash(request, exc.message, "error")
        return RedirectResponse(day_target, status_code=303)
    flash(request, message, "success")
    return RedirectResponse(day_target, status_code=303)
