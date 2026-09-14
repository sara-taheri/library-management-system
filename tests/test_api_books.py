"""Tests for the read-only books API (Phase 2)."""
from app.models import Book


def test_list_books_empty_catalog(client):
    response = client.get("/api/books")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_list_books(seeded_client):
    body = seeded_client.get("/api/books").json()
    assert body["total"] == 3
    titles = [item["title"] for item in body["items"]]
    assert "Harry Potter" in titles
    assert "Hamlet" in titles


def test_list_books_exposes_availability(seeded_client):
    body = seeded_client.get("/api/books").json()
    harry = next(b for b in body["items"] if b["id"] == 1)
    assert harry["total_copies"] == 5
    assert harry["available_copies"] == 4
    assert harry["is_available"] is True


def test_search_by_title(seeded_client):
    body = seeded_client.get("/api/books", params={"q": "hamlet"}).json()
    assert body["total"] == 1
    assert body["items"][0]["author"] == "William Shakespeare"


def test_search_by_author(seeded_client):
    body = seeded_client.get("/api/books", params={"q": "rowling"}).json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Harry Potter"


def test_search_without_match(seeded_client):
    body = seeded_client.get("/api/books", params={"q": "nonexistent"}).json()
    assert body["total"] == 0


def test_filter_by_genre(seeded_client):
    body = seeded_client.get("/api/books", params={"genre": "romance"}).json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "The Notebook"


def test_filter_available_only(seeded_app, seeded_client):
    # Make one book fully borrowed out.
    with seeded_app.state.session_factory() as db:
        book = db.get(Book, 1)
        book.available_copies = 0
        db.commit()

    body = seeded_client.get("/api/books", params={"available_only": "true"}).json()
    assert body["total"] == 2
    assert all(item["is_available"] for item in body["items"])


def test_book_detail(seeded_client):
    response = seeded_client.get("/api/books/2")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "The Notebook"
    assert body["author"] == "Nicholas Sparks"
    assert body["is_available"] is True


def test_book_detail_not_found(seeded_client):
    response = seeded_client.get("/api/books/999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Book not found"


def test_book_detail_rejects_non_integer_id(seeded_client):
    response = seeded_client.get("/api/books/abc")
    assert response.status_code == 422


def test_pagination(seeded_client):
    body = seeded_client.get(
        "/api/books", params={"page": 1, "page_size": 2}
    ).json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["pages"] == 2

    body_page2 = seeded_client.get(
        "/api/books", params={"page": 2, "page_size": 2}
    ).json()
    assert len(body_page2["items"]) == 1
