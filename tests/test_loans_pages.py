"""Server-rendered borrowing/returning page tests (Checkpoint 2)."""
import html
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import utcnow
from app.models import Book, Loan
from tests.conftest import csrf_token_from, make_user, page_login


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


def _borrow_via_page(client, book_id):
    """Click the Borrow button on the book detail page, like a browser."""
    page = client.get(f"/books/{book_id}")
    token = csrf_token_from(page.text)
    response = client.post(
        f"/books/{book_id}/borrow", data={"_csrf": token}, follow_redirects=False
    )
    assert response.status_code == 303
    return response


def _loan_id_from(page_html) -> str:
    match = re.search(r'action="/loans/(\d+)/return"', page_html)
    assert match, "return form not found"
    return match.group(1)


def _logout(client):
    """End the current page session (the login page redirects signed-in
    users, so tests must log out before switching accounts)."""
    token = csrf_token_from(client.get("/").text)  # navbar logout form
    response = client.post("/logout", data={"_csrf": token}, follow_redirects=False)
    assert response.status_code == 303


# ------------------------------------------------------------ detail page


def test_detail_page_borrow_states(library_client):
    guest = library_client.get("/books/1")
    assert "Log in" in guest.text and "to borrow this book" in guest.text

    page_login(library_client, "alice", "alicepass123")
    page = library_client.get("/books/1")
    assert "Borrow this book" in page.text
    assert 'action="/books/1/borrow"' in page.text

    borrowed = _borrow_via_page(library_client, 1)
    assert borrowed.headers["location"] == "/books/1"
    after = library_client.get("/books/1")
    # flash confirmation (titles are HTML-escaped in the rendered page)
    assert "Borrowed 'Harry Potter'" in html.unescape(after.text)
    assert "Return book" in after.text
    assert "due" in after.text.lower()
    assert "Borrow this book" not in after.text


def test_detail_page_all_copies_on_loan(library_client, library_app):
    with library_app.state.session_factory() as db:
        db.get(Book, 2).available_copies = 0
        db.commit()
    page_login(library_client, "alice", "alicepass123")
    assert "All copies are currently on loan" in library_client.get("/books/2").text


def test_borrow_post_requires_login(library_client):
    response = library_client.post(
        "/books/1/borrow", data={"_csrf": "x"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_duplicate_borrow_shows_flash_error(library_client):
    page_login(library_client, "alice", "alicepass123")
    _borrow_via_page(library_client, 1)
    token = csrf_token_from(library_client.get("/books/1").text)
    again = library_client.post(
        "/books/1/borrow", data={"_csrf": token}, follow_redirects=False
    )
    page = library_client.get(again.headers["location"])
    assert "already borrowed" in page.text


# ---------------------------------------------------------- account page


def test_account_shows_active_loans_and_history(library_client):
    page_login(library_client, "alice", "alicepass123")
    _borrow_via_page(library_client, 1)

    account = library_client.get("/account")
    assert "Currently borrowed" in account.text
    assert "Harry Potter" in account.text
    assert "On time" in account.text

    loan_id = _loan_id_from(account.text)
    token = csrf_token_from(account.text)
    returned = library_client.post(
        f"/loans/{loan_id}/return",
        data={"_csrf": token, "next": "/account"},
        follow_redirects=False,
    )
    assert returned.status_code == 303
    assert returned.headers["location"] == "/account"

    after_text = html.unescape(library_client.get("/account").text)
    assert "Returned 'Harry Potter'" in after_text  # flash
    assert "Nothing borrowed right now" in after_text
    history = after_text.split("Borrowing history")[1]
    assert "Harry Potter" in history


def test_overdue_badge(library_client, library_app):
    page_login(library_client, "alice", "alicepass123")
    _borrow_via_page(library_client, 1)

    with library_app.state.session_factory() as db:
        loan = db.scalar(select(Loan))
        loan.due_at = utcnow() - timedelta(days=1)
        db.commit()

    assert "Overdue" in library_client.get("/account").text
    assert "Overdue" in library_client.get("/books/1").text


def test_member_cannot_return_others_loan_via_page(library_client):
    page_login(library_client, "alice", "alicepass123")
    _borrow_via_page(library_client, 1)
    loan_id = _loan_id_from(library_client.get("/account").text)

    _logout(library_client)
    page_login(library_client, "bob", "bobpass123")
    token = csrf_token_from(library_client.get("/account").text)
    response = library_client.post(
        f"/loans/{loan_id}/return",
        data={"_csrf": token, "next": "/account"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "own loans" in library_client.get(response.headers["location"]).text

    # Alice's loan is still active.
    _logout(library_client)
    page_login(library_client, "alice", "alicepass123")
    account = library_client.get("/account").text
    assert "Harry Potter" in account
    assert _loan_id_from(account) == loan_id  # still borrowable/returnable


# ------------------------------------------------------------ admin page


def test_admin_loans_page(library_client):
    page_login(library_client, "alice", "alicepass123")
    _borrow_via_page(library_client, 1)
    _borrow_via_page(library_client, 2)

    _logout(library_client)
    page_login(library_client, "bob", "bobpass123")
    denied = library_client.get("/admin/loans", follow_redirects=False)
    assert denied.status_code == 303
    assert denied.headers["location"] == "/admin"

    _logout(library_client)
    page_login(library_client, "root", "rootpass123")
    page = library_client.get("/admin/loans")
    assert page.status_code == 200
    assert "2 loans" in page.text
    assert "alice" in page.text
    assert "Harry Potter" in page.text and "The Notebook" in page.text

    # Admin returns one of alice's loans straight from this page.
    loan_id = _loan_id_from(page.text)
    token = csrf_token_from(page.text)
    response = library_client.post(
        f"/loans/{loan_id}/return",
        data={"_csrf": token, "next": "/admin/loans"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/admin/loans"

    updated = library_client.get("/admin/loans")
    assert "Returned" in updated.text
    returned_only = library_client.get("/admin/loans", params={"status": "returned"})
    assert "1 loan" in returned_only.text
    active_only = library_client.get("/admin/loans", params={"status": "active"})
    assert "1 loan" in active_only.text
