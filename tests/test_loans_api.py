"""Loans API tests (Checkpoint 2: borrowing and returning).

Fixtures build a small library: the seeded 3-book catalog plus members
alice/bob and admin root. Books: 1 Harry Potter (5 total / 4 free),
2 The Notebook (4/4), 3 Hamlet (7/7).
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import settings
from app.models import (
    Book,
    CalendarEvent,
    EventStatus,
    EventType,
    Loan,
    LoanStatus,
    User,
)
from tests.conftest import api_login, make_user


@pytest.fixture()
def library_app(seeded_app):
    make_user(seeded_app, "alice", "alicepass123")
    make_user(seeded_app, "bob", "bobpass123")
    make_user(seeded_app, "root", "rootpass123", role="admin")
    return seeded_app


@pytest.fixture()
def library_client(library_app):
    with TestClient(library_app) as test_client:
        yield test_client


def _login(client, username, password):
    response = api_login(client, username, password)
    assert response.status_code == 200, response.text
    return client


def _user_id(app, username) -> int:
    with app.state.session_factory() as db:
        return db.scalar(select(User.id).where(User.username == username))


def _borrow(client, book_id, username="alice", password="alicepass123"):
    _login(client, username, password)
    response = client.post("/api/loans", json={"book_id": book_id})
    return response


# ---------------------------------------------------------------- borrowing


def test_borrow_success(library_client):
    response = _borrow(library_client, 1)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "active"
    assert body["book_id"] == 1
    assert body["book_title"] == "Harry Potter"
    assert body["borrower"] == "alice"
    assert body["returned_at"] is None
    assert body["is_overdue"] is False

    borrowed = datetime.fromisoformat(body["borrowed_at"])
    due = datetime.fromisoformat(body["due_at"])
    assert due - borrowed == timedelta(days=settings.loan_period_days)

    # Availability decremented exactly once.
    assert library_client.get("/api/books/1").json()["available_copies"] == 3


def test_borrow_requires_login(library_client):
    assert library_client.post("/api/loans", json={"book_id": 1}).status_code == 401


def test_borrow_unknown_book_is_404(library_client):
    assert _borrow(library_client, 9999).status_code == 404


def test_borrow_deactivated_book_rejected(library_client):
    _login(library_client, "root", "rootpass123")
    assert library_client.delete("/api/books/2").status_code == 200  # deactivate
    response = _borrow(library_client, 2)
    assert response.status_code == 400
    assert "active catalog" in response.json()["detail"]


def test_borrow_duplicate_active_rejected(library_client):
    first = _borrow(library_client, 1)
    assert first.status_code == 201
    second = _borrow(library_client, 1)
    assert second.status_code == 409
    assert "already borrowed" in second.json()["detail"]
    # Availability was decremented only once.
    assert library_client.get("/api/books/1").json()["available_copies"] == 3
    # A different book is still borrowable by the same member.
    assert _borrow(library_client, 2).status_code == 201


def test_borrow_unavailable_copy_rejected(library_client):
    _login(library_client, "root", "rootpass123")
    created = library_client.post(
        "/api/books",
        json={"title": "Single Copy", "author": "Someone", "total_copies": 1},
    ).json()

    assert _borrow(library_client, created["id"]).status_code == 201  # alice
    bob = _borrow(library_client, created["id"], "bob", "bobpass123")
    assert bob.status_code == 409
    assert "on loan" in bob.json()["detail"]
    assert library_client.get(f"/api/books/{created['id']}").json()["available_copies"] == 0


# --------------------------------------------------------------- returning


def test_return_flow(library_client):
    loan = _borrow(library_client, 1).json()
    response = library_client.post(f"/api/loans/{loan['id']}/return")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "returned"
    assert body["returned_at"] is not None
    assert body["is_overdue"] is False
    # Availability restored.
    assert library_client.get("/api/books/1").json()["available_copies"] == 4

    again = library_client.post(f"/api/loans/{loan['id']}/return")
    assert again.status_code == 409
    assert "already returned" in again.json()["detail"]


def test_return_requires_login(library_client):
    assert library_client.post("/api/loans/1/return").status_code == 401


def test_return_permissions(library_client, library_app):
    loan = _borrow(library_client, 1).json()

    _login(library_client, "bob", "bobpass123")
    denied = library_client.post(f"/api/loans/{loan['id']}/return")
    assert denied.status_code == 403
    assert "own loans" in denied.json()["detail"]

    # The loan is untouched, and an admin may return it for the member.
    _login(library_client, "root", "rootpass123")
    admin_return = library_client.post(f"/api/loans/{loan['id']}/return")
    assert admin_return.status_code == 200
    assert admin_return.json()["status"] == "returned"


# ------------------------------------------------------------------ history


def test_my_loans_history(library_client):
    assert _borrow(library_client, 1).status_code == 201
    assert _borrow(library_client, 2).status_code == 201

    mine = library_client.get("/api/loans/me").json()
    assert mine["total"] == 2
    assert all(item["borrower"] == "alice" for item in mine["items"])

    loan_book1 = next(l for l in mine["items"] if l["book_id"] == 1)
    library_client.post(f"/api/loans/{loan_book1['id']}/return")

    active = library_client.get("/api/loans/me", params={"status": "active"}).json()
    assert active["total"] == 1 and active["items"][0]["book_id"] == 2
    returned = library_client.get("/api/loans/me", params={"status": "returned"}).json()
    assert returned["total"] == 1 and returned["items"][0]["book_id"] == 1

    # Bob sees none of alice's loans.
    _login(library_client, "bob", "bobpass123")
    assert library_client.get("/api/loans/me").json()["total"] == 0

    # Invalid status filter is rejected.
    assert library_client.get(
        "/api/loans/me", params={"status": "bogus"}
    ).status_code == 422


def test_admin_sees_all_loans(library_client, library_app):
    assert _borrow(library_client, 1).status_code == 201
    assert _borrow(library_client, 3, "bob", "bobpass123").status_code == 201

    # Guests and members cannot list all loans.
    library_client.cookies.clear()
    assert library_client.get("/api/loans").status_code == 401
    _login(library_client, "alice", "alicepass123")
    assert library_client.get("/api/loans").status_code == 403

    _login(library_client, "root", "rootpass123")
    all_loans = library_client.get("/api/loans").json()
    assert all_loans["total"] == 2
    borrowers = {item["borrower"] for item in all_loans["items"]}
    assert borrowers == {"alice", "bob"}

    alice_only = library_client.get(
        "/api/loans", params={"user_id": _user_id(library_app, "alice")}
    ).json()
    assert alice_only["total"] == 1


def test_loan_detail_access(library_client):
    loan = _borrow(library_client, 1).json()

    assert library_client.get(f"/api/loans/{loan['id']}").status_code == 200  # owner
    _login(library_client, "bob", "bobpass123")
    assert library_client.get(f"/api/loans/{loan['id']}").status_code == 403
    _login(library_client, "root", "rootpass123")
    assert library_client.get(f"/api/loans/{loan['id']}").status_code == 200
    assert library_client.get("/api/loans/9999").status_code == 404


# ------------------------------------------------- calendar link + integrity


def test_book_return_event_auto_created(library_client, library_app):
    loan = _borrow(library_client, 1).json()
    alice_id = _user_id(library_app, "alice")

    with library_app.state.session_factory() as db:
        events = db.scalars(
            select(CalendarEvent).where(CalendarEvent.loan_id == loan["id"])
        ).all()
    assert len(events) == 1
    event = events[0]
    assert event.event_type == EventType.BOOK_RETURN.value
    assert event.created_by == alice_id
    assert "Harry Potter" in event.title
    assert event.event_date == datetime.fromisoformat(loan["due_at"])
    assert event.book_id == 1
    # It is a pending runner task scheduled for the due date.
    assert event.status == EventStatus.PENDING.value
    assert event.scheduled_at == event.event_date


def test_return_cancels_book_return_event(library_client, library_app):
    loan = _borrow(library_client, 1).json()
    library_client.post(f"/api/loans/{loan['id']}/return")
    with library_app.state.session_factory() as db:
        events = db.scalars(
            select(CalendarEvent).where(CalendarEvent.loan_id == loan["id"])
        ).all()
    assert len(events) == 1  # history is preserved...
    assert events[0].status == EventStatus.CANCELLED.value  # ...but cancelled


def test_availability_consistency_after_mixed_operations(library_client, library_app):
    """For every book: available == total - (number of active loans)."""
    # The seeded catalog mimics the legacy data (Harry Potter starts at
    # 4/5 with no matching Loan row), so normalise availability first.
    with library_app.state.session_factory() as db:
        for book in db.scalars(select(Book)).all():
            book.available_copies = book.total_copies
        db.commit()

    assert _borrow(library_client, 1).status_code == 201                       # alice b1
    assert _borrow(library_client, 2).status_code == 201                       # alice b2
    assert _borrow(library_client, 1, "bob", "bobpass123").status_code == 201  # bob b1
    _login(library_client, "alice", "alicepass123")
    alice_loan_b1 = library_client.get(
        "/api/loans/me", params={"status": "active"}
    ).json()["items"]
    target = next(l for l in alice_loan_b1 if l["book_id"] == 1)
    assert library_client.post(f"/api/loans/{target['id']}/return").status_code == 200

    with library_app.state.session_factory() as db:
        for book in db.scalars(select(Book)).all():
            active = db.scalar(
                select(func.count())
                .select_from(Loan)
                .where(
                    Loan.book_id == book.id,
                    Loan.status == LoanStatus.ACTIVE.value,
                )
            )
            assert book.available_copies == book.total_copies - active, book.title
            assert 0 <= book.available_copies <= book.total_copies
