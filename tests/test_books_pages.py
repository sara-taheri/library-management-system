"""Server-rendered catalog page tests (Checkpoint 1).

Covers browsing/search for everyone and the admin-only management forms
(create / edit / deactivate) driven exactly like a browser would.
"""
import pytest

from app.models import Book
from tests.conftest import csrf_token_from, make_user, page_login


@pytest.fixture()
def seeded_admin(seeded_app):
    make_user(seeded_app, "seedadmin", "adminpass123", role="admin")
    return {"username": "seedadmin", "password": "adminpass123"}


@pytest.fixture()
def seeded_member(seeded_app):
    make_user(seeded_app, "seedmember", "memberpass123")
    return {"username": "seedmember", "password": "memberpass123"}


# ---------------------------------------------------------------- browsing


def test_catalog_page_is_public(seeded_client):
    response = seeded_client.get("/books")
    assert response.status_code == 200
    assert "Harry Potter" in response.text
    assert "Hamlet" in response.text
    assert "3 books found" in response.text
    assert "/books/new" not in response.text  # no management UI for guests


def test_catalog_search(seeded_client):
    response = seeded_client.get("/books", params={"q": "hamlet"})
    assert "Hamlet" in response.text
    assert "Harry Potter" not in response.text
    assert "1 book found" in response.text


def test_catalog_genre_and_availability_filters(seeded_client, seeded_app):
    by_genre = seeded_client.get("/books", params={"genre": "fantasy"})
    assert "Harry Potter" in by_genre.text
    assert "Hamlet" not in by_genre.text

    with seeded_app.state.session_factory() as db:
        db.get(Book, 3).available_copies = 0  # Hamlet fully on loan
        db.commit()

    available = seeded_client.get("/books", params={"available": "1"})
    assert "Hamlet" not in available.text
    assert "Harry Potter" in available.text


def test_book_detail_page(seeded_client):
    response = seeded_client.get("/books/1")
    assert response.status_code == 200
    assert "Harry Potter" in response.text
    assert "J.K. Rowling" in response.text
    assert "4 available of 5" in response.text

    assert seeded_client.get("/books/999").status_code == 404


# ------------------------------------------------------- admin-only access


def test_new_book_page_redirects_guests_to_login(seeded_client):
    response = seeded_client.get("/books/new", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_member_denied_management_pages(seeded_client, seeded_member):
    page_login(seeded_client, **seeded_member)

    response = seeded_client.get("/books/new", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/books"
    assert "Access denied" in seeded_client.get("/books").text  # flash

    edit = seeded_client.get("/books/1/edit", follow_redirects=False)
    assert edit.status_code == 303

    token = csrf_token_from(seeded_client.get("/books/1").text)
    delete = seeded_client.post(
        "/books/1/delete", data={"_csrf": token}, follow_redirects=False
    )
    assert delete.status_code == 303
    # The book was NOT deactivated by the member's attempt.
    assert "Harry Potter" in seeded_client.get("/books").text


# ------------------------------------------------------------ admin flows


def test_admin_creates_book_via_page(seeded_client, seeded_admin):
    page_login(seeded_client, **seeded_admin)
    form_page = seeded_client.get("/books/new")
    assert "Add a book" in form_page.text

    response = seeded_client.post(
        "/books/new",
        data={
            "title": "Dune",
            "author": "Frank Herbert",
            "isbn": "",
            "genre": "Sci-Fi",
            "description": "The spice must flow.",
            "total_copies": "3",
            "_csrf": csrf_token_from(form_page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail = seeded_client.get(response.headers["location"])
    assert "Dune" in detail.text
    assert "3 available of 3" in detail.text
    assert "added to the catalog" in detail.text  # flash message
    assert "Dune" in seeded_client.get("/books").text


def test_create_page_shows_service_errors(seeded_client, seeded_admin):
    page_login(seeded_client, **seeded_admin)
    token = csrf_token_from(seeded_client.get("/books/new").text)

    duplicate = seeded_client.post(
        "/books/new",
        data={
            "title": "Harry Potter",
            "author": "J.K. Rowling",
            "isbn": "",
            "genre": "",
            "description": "",
            "total_copies": "1",
            "_csrf": token,
        },
    )
    assert duplicate.status_code == 200  # form re-rendered, not a redirect
    assert "already exists" in duplicate.text

    empty = seeded_client.post(
        "/books/new",
        data={
            "title": "",
            "author": "",
            "isbn": "",
            "genre": "",
            "description": "",
            "total_copies": "1",
            "_csrf": token,
        },
    )
    assert empty.status_code == 200
    assert "Title and author are required" in empty.text

    bad_copies = seeded_client.post(
        "/books/new",
        data={
            "title": "Something",
            "author": "Someone",
            "isbn": "",
            "genre": "",
            "description": "",
            "total_copies": "abc",
            "_csrf": token,
        },
    )
    assert bad_copies.status_code == 200
    assert "whole number" in bad_copies.text


def test_create_page_rejects_invalid_csrf(seeded_client, seeded_admin):
    page_login(seeded_client, **seeded_admin)
    response = seeded_client.post(
        "/books/new",
        data={
            "title": "Nope",
            "author": "Nobody",
            "total_copies": "1",
            "_csrf": "forged-token",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "Nope" not in seeded_client.get("/books", params={"all": "1"}).text


def test_admin_edits_book_via_page(seeded_client, seeded_admin):
    page_login(seeded_client, **seeded_admin)
    edit_page = seeded_client.get("/books/1/edit")
    assert 'value="Harry Potter"' in edit_page.text

    response = seeded_client.post(
        "/books/1/edit",
        data={
            "title": "Harry Potter and the Philosopher's Stone",
            "author": "J.K. Rowling",
            "isbn": "",
            "genre": "Fantasy",
            "description": "",
            "total_copies": "5",
            "is_active": "on",
            "_csrf": csrf_token_from(edit_page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/books/1"
    assert "Philosopher" in seeded_client.get("/books/1").text


def test_edit_page_protects_copies_on_loan(seeded_client, seeded_admin):
    """Seeded Harry Potter: 5 total, 4 available => 1 copy on loan."""
    page_login(seeded_client, **seeded_admin)
    token = csrf_token_from(seeded_client.get("/books/1/edit").text)
    response = seeded_client.post(
        "/books/1/edit",
        data={
            "title": "Harry Potter",
            "author": "J.K. Rowling",
            "isbn": "",
            "genre": "Fantasy",
            "description": "",
            "total_copies": "0",  # below the 1 copy on loan
            "is_active": "on",
            "_csrf": token,
        },
    )
    assert response.status_code == 200  # re-rendered with the error
    assert "on loan" in response.text


def test_admin_deactivates_via_page(seeded_client, seeded_admin):
    page_login(seeded_client, **seeded_admin)
    token = csrf_token_from(seeded_client.get("/books/2").text)

    response = seeded_client.post(
        "/books/2/delete", data={"_csrf": token}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/books"

    listing = seeded_client.get("/books")
    assert "deactivated" in listing.text  # flash confirmation
    # Hidden from the catalog rows (the flash message itself quotes the
    # title, so assert on the row link specifically).
    assert '/books/2">The Notebook</a>' not in listing.text

    admin_view = seeded_client.get("/books", params={"all": "1"})
    assert '/books/2">The Notebook</a>' in admin_view.text
    assert "Deactivated" in admin_view.text
    assert seeded_client.get("/books/2").status_code == 200  # admins still see it

    # After logout, the deactivated book is gone for guests (404 detail).
    logout_token = csrf_token_from(seeded_client.get("/books").text)
    seeded_client.post("/logout", data={"_csrf": logout_token})
    assert seeded_client.get("/books/2").status_code == 404
