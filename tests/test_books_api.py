"""Admin book-management API tests (Checkpoint 1).

The public read behavior of GET /api/books is covered by
tests/test_api_books.py (Phase 2); this module covers the new
create/update/delete endpoints, their validation rules and permissions.
"""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.database import utcnow
from app.models import Book, Loan, User
from tests.conftest import api_login

DUNE = {
    "title": "Dune",
    "author": "Frank Herbert",
    "genre": "Sci-Fi",
    "isbn": "978-0441172719",
    "total_copies": 3,
}


@pytest.fixture()
def admin_client(client, admin_account):
    api_login(client, **admin_account)
    return client


@pytest.fixture()
def member_client(client, member_account):
    api_login(client, **member_account)
    return client


def _book_row(app, **overrides) -> int:
    """Insert a book directly into the test DB; returns its id."""
    data = {
        "title": "Seed Book",
        "author": "Seed Author",
        "total_copies": 2,
        "available_copies": 2,
    }
    data.update(overrides)
    with app.state.session_factory() as db:
        book = Book(**data)
        db.add(book)
        db.commit()
        return book.id


def _loan_row(app, user_id: int, book_id: int) -> None:
    with app.state.session_factory() as db:
        db.add(
            Loan(
                user_id=user_id,
                book_id=book_id,
                due_at=utcnow() + timedelta(days=14),
            )
        )
        db.commit()


# ------------------------------------------------------------------ create


def test_create_book_as_admin(admin_client):
    response = admin_client.post("/api/books", json=DUNE)
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Dune"
    assert body["author"] == "Frank Herbert"
    assert body["total_copies"] == 3
    assert body["available_copies"] == 3
    assert body["is_active"] is True
    assert body["is_available"] is True


def test_create_book_anonymous_rejected(client):
    assert client.post("/api/books", json=DUNE).status_code == 401


def test_create_book_member_forbidden(member_client):
    assert member_client.post("/api/books", json=DUNE).status_code == 403


def test_create_book_validation_errors(admin_client):
    missing_title = admin_client.post("/api/books", json={"author": "X"})
    assert missing_title.status_code == 422
    empty_title = admin_client.post("/api/books", json={**DUNE, "title": ""})
    assert empty_title.status_code == 422
    zero_copies = admin_client.post("/api/books", json={**DUNE, "total_copies": 0})
    assert zero_copies.status_code == 422


def test_create_book_duplicate_title_author_conflict(admin_client):
    assert admin_client.post("/api/books", json=DUNE).status_code == 201
    duplicate = admin_client.post(
        "/api/books",
        json={**DUNE, "title": "dune", "author": "frank herbert", "isbn": None},
    )
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]


def test_create_book_duplicate_isbn_conflict(admin_client):
    assert admin_client.post("/api/books", json=DUNE).status_code == 201
    duplicate = admin_client.post(
        "/api/books", json={**DUNE, "title": "Other Book", "author": "Someone Else"}
    )
    assert duplicate.status_code == 409
    assert "ISBN" in duplicate.json()["detail"]


# ------------------------------------------------------------------ update


def test_update_book_as_admin(admin_client):
    created = admin_client.post("/api/books", json=DUNE).json()
    response = admin_client.put(
        f"/api/books/{created['id']}",
        json={"genre": "Classic", "description": "The spice must flow."},
    )
    assert response.status_code == 200
    assert response.json()["genre"] == "Classic"
    assert response.json()["description"] == "The spice must flow."
    assert response.json()["title"] == "Dune"  # untouched fields persist


def test_update_total_copies_shifts_availability(admin_client, app):
    # 3 total, 1 available  =>  2 copies on loan
    book_id = _book_row(app, title="On Loan Book", total_copies=3, available_copies=1)

    grow = admin_client.put(f"/api/books/{book_id}", json={"total_copies": 5})
    assert grow.status_code == 200
    assert grow.json()["total_copies"] == 5
    assert grow.json()["available_copies"] == 3  # +2 free copies

    blocked = admin_client.put(f"/api/books/{book_id}", json={"total_copies": 1})
    assert blocked.status_code == 400
    assert "on loan" in blocked.json()["detail"]

    shrink = admin_client.put(f"/api/books/{book_id}", json={"total_copies": 2})
    assert shrink.status_code == 200
    assert shrink.json()["available_copies"] == 0  # exactly the on-loan floor


def test_update_clears_nullable_fields(admin_client):
    created = admin_client.post("/api/books", json=DUNE).json()
    response = admin_client.put(
        f"/api/books/{created['id']}", json={"isbn": None, "genre": None}
    )
    assert response.status_code == 200
    assert response.json()["isbn"] is None
    assert response.json()["genre"] is None


def test_update_without_fields_is_400(admin_client):
    created = admin_client.post("/api/books", json=DUNE).json()
    response = admin_client.put(f"/api/books/{created['id']}", json={})
    assert response.status_code == 400


def test_update_missing_book_is_404(admin_client):
    assert admin_client.put("/api/books/9999", json={"title": "X"}).status_code == 404


def test_update_member_forbidden(member_client, app):
    book_id = _book_row(app)
    response = member_client.put(f"/api/books/{book_id}", json={"title": "Hacked"})
    assert response.status_code == 403


# ------------------------------------------------------------------ delete


def test_delete_deactivates_by_default(admin_client):
    created = admin_client.post("/api/books", json=DUNE).json()
    response = admin_client.delete(f"/api/books/{created['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is False
    assert "deactivated" in body["message"]
    assert body["book"]["is_active"] is False

    default_listing = admin_client.get("/api/books").json()
    assert created["id"] not in [b["id"] for b in default_listing["items"]]

    full_listing = admin_client.get(
        "/api/books", params={"include_inactive": "true"}
    ).json()
    assert created["id"] in [b["id"] for b in full_listing["items"]]

    detail = admin_client.get(f"/api/books/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["is_active"] is False


def test_delete_twice_conflicts(admin_client):
    created = admin_client.post("/api/books", json=DUNE).json()
    assert admin_client.delete(f"/api/books/{created['id']}").status_code == 200
    second = admin_client.delete(f"/api/books/{created['id']}")
    assert second.status_code == 409
    assert "already deactivated" in second.json()["detail"]


def test_hard_delete_when_no_loans(admin_client):
    created = admin_client.post("/api/books", json=DUNE).json()
    response = admin_client.delete(
        f"/api/books/{created['id']}", params={"hard": "true"}
    )
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert admin_client.get(f"/api/books/{created['id']}").status_code == 404


def test_hard_delete_blocked_when_loans_exist(admin_client, app):
    created = admin_client.post("/api/books", json=DUNE).json()
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "testadmin"))
    _loan_row(app, user_id=user.id, book_id=created["id"])

    response = admin_client.delete(
        f"/api/books/{created['id']}", params={"hard": "true"}
    )
    assert response.status_code == 409
    assert "loan record" in response.json()["detail"]

    # The book is untouched and can still be safely deactivated.
    detail = admin_client.get(f"/api/books/{created['id']}")
    assert detail.status_code == 200 and detail.json()["is_active"] is True
    assert admin_client.delete(f"/api/books/{created['id']}").status_code == 200


def test_delete_member_forbidden(member_client, app):
    book_id = _book_row(app)
    assert member_client.delete(f"/api/books/{book_id}").status_code == 403


def test_delete_anonymous_rejected(client):
    assert client.delete("/api/books/1").status_code == 401


# ------------------------------------------------------- contract smoke test


def test_public_listing_contract_unchanged(client, app):
    """Phase-2 clients keep working: same fields, active books only."""
    _book_row(app, title="Visible Book")
    _book_row(app, title="Hidden Book", is_active=False)

    body = client.get("/api/books").json()
    assert set(body) == {"items", "total", "page", "page_size", "pages"}
    titles = [b["title"] for b in body["items"]]
    assert "Visible Book" in titles and "Hidden Book" not in titles
    item = body["items"][0]
    assert item["is_available"] is True  # computed field still present
