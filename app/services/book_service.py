"""Book catalog business logic (Checkpoint 1).

Single source of truth for listing/searching/managing books - used by
both the JSON API and the server-rendered catalog pages. Read access is
public; the routers enforce admin-only access for write operations.

Deletion policy:
- default DELETE = **deactivate** (soft delete): the book leaves the
  catalog but its loan history stays intact,
- `hard=True` permanently deletes a book, but only when no loan record
  references it (otherwise 409 with a helpful message).
"""
import logging

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Book, CalendarEvent, Loan

logger = logging.getLogger("app.books")


class BookError(Exception):
    """User-facing book-management error (status_code maps to HTTP)."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ------------------------------------------------------------------- reads


def list_books(
    db: Session,
    *,
    q: str | None = None,
    genre: str | None = None,
    available_only: bool = False,
    include_inactive: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Book], int, int]:
    """Return (items, total, pages) for the filtered catalog."""
    stmt = select(Book)
    if not include_inactive:
        stmt = stmt.where(Book.is_active.is_(True))
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(Book.title.ilike(pattern), Book.author.ilike(pattern)))
    if genre and genre.strip():
        stmt = stmt.where(func.lower(Book.genre) == genre.strip().lower())
    if available_only:
        stmt = stmt.where(Book.available_copies > 0)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db.scalars(
            stmt.order_by(Book.title, Book.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    pages = max(1, -(-total // page_size))  # ceil division
    return items, total, pages


def get_book(db: Session, book_id: int) -> Book | None:
    return db.get(Book, book_id)


# ------------------------------------------------------------------ writes


def create_book(
    db: Session,
    *,
    title: str,
    author: str,
    isbn: str | None = None,
    genre: str | None = None,
    description: str | None = None,
    total_copies: int = 1,
) -> Book:
    title = (title or "").strip()
    author = (author or "").strip()
    isbn = (isbn or "").strip() or None
    genre = (genre or "").strip() or None
    description = (description or "").strip() or None

    if not title or not author:
        raise BookError("Title and author are required.")
    if total_copies < 1:
        raise BookError("A book needs at least one copy.")

    duplicate = db.scalar(
        select(Book).where(
            func.lower(Book.title) == title.lower(),
            func.lower(Book.author) == author.lower(),
        )
    )
    if duplicate is not None:
        raise BookError(
            f"'{duplicate.title}' by {duplicate.author} already exists "
            f"(ID {duplicate.id}). Edit that book to change its copies.",
            status_code=409,
        )
    if isbn is not None:
        isbn_taken = db.scalar(select(Book).where(Book.isbn == isbn))
        if isbn_taken is not None:
            raise BookError(
                f"ISBN {isbn} is already used by '{isbn_taken.title}' "
                f"(ID {isbn_taken.id}).",
                status_code=409,
            )

    book = Book(
        title=title,
        author=author,
        isbn=isbn,
        genre=genre,
        description=description,
        total_copies=total_copies,
        available_copies=total_copies,
    )
    db.add(book)
    db.commit()
    logger.info("Created book %r (id=%s, copies=%s)", book.title, book.id, total_copies)
    return book


def update_book(db: Session, book_id: int, fields: dict) -> Book:
    """Apply a partial update. `fields` comes from BookUpdate(exclude_unset)."""
    book = db.get(Book, book_id)
    if book is None:
        raise BookError("Book not found.", status_code=404)

    fields = dict(fields)  # do not mutate the caller's dict
    fields.pop("available_copies", None)  # derived value, never set directly

    for name in ("title", "author"):
        if name in fields:
            value = (fields[name] or "").strip()
            if not value:
                raise BookError(f"{name.capitalize()} cannot be empty.")
            fields[name] = value
    for name in ("isbn", "genre", "description"):
        if name in fields:
            fields[name] = (fields[name] or "").strip() or None

    # Uniqueness checks against the *resulting* values, excluding this book.
    new_title = fields.get("title", book.title)
    new_author = fields.get("author", book.author)
    if (new_title.lower(), new_author.lower()) != (book.title.lower(), book.author.lower()):
        duplicate = db.scalar(
            select(Book).where(
                func.lower(Book.title) == new_title.lower(),
                func.lower(Book.author) == new_author.lower(),
                Book.id != book.id,
            )
        )
        if duplicate is not None:
            raise BookError(
                f"'{duplicate.title}' by {duplicate.author} already exists "
                f"(ID {duplicate.id}).",
                status_code=409,
            )
    new_isbn = fields.get("isbn", book.isbn)
    if new_isbn and new_isbn != book.isbn:
        isbn_taken = db.scalar(
            select(Book).where(Book.isbn == new_isbn, Book.id != book.id)
        )
        if isbn_taken is not None:
            raise BookError(
                f"ISBN {new_isbn} is already used by '{isbn_taken.title}'.",
                status_code=409,
            )

    # Copy-count changes shift availability by the same delta, but never
    # below the number of copies currently on loan.
    if fields.get("total_copies") is not None and "total_copies" in fields:
        new_total = int(fields.pop("total_copies"))
        if new_total < 0:
            raise BookError("Total copies cannot be negative.")
        on_loan = book.total_copies - book.available_copies
        if new_total < on_loan:
            raise BookError(
                f"{on_loan} cop{'y is' if on_loan == 1 else 'ies are'} currently "
                f"on loan; the total cannot go below that."
            )
        book.available_copies += new_total - book.total_copies
        book.total_copies = new_total

    # Nullable text fields: an explicit null clears the value.
    for name in ("title", "author", "isbn", "genre", "description"):
        if name in fields:
            setattr(book, name, fields[name])
    if "is_active" in fields and fields["is_active"] is not None:
        book.is_active = bool(fields["is_active"])

    db.commit()
    logger.info("Updated book id=%s (%s)", book.id, book.title)
    return book


def delete_book(db: Session, book_id: int, *, hard: bool = False) -> dict:
    """Deactivate (default) or permanently delete a book."""
    book = db.get(Book, book_id)
    if book is None:
        raise BookError("Book not found.", status_code=404)

    if not hard:
        if not book.is_active:
            raise BookError(
                f"'{book.title}' is already deactivated.", status_code=409
            )
        book.is_active = False
        db.commit()
        logger.info("Deactivated book id=%s (%s)", book.id, book.title)
        return {
            "deleted": False,
            "message": (
                f"'{book.title}' was deactivated: it is hidden from the "
                "catalog, but its borrowing history is preserved."
            ),
            "book": book,
        }

    loan_count = (
        db.scalar(select(func.count()).select_from(Loan).where(Loan.book_id == book.id))
        or 0
    )
    if loan_count:
        raise BookError(
            f"'{book.title}' has {loan_count} loan record(s) and cannot be "
            "permanently deleted. Deactivate it instead (history is kept).",
            status_code=409,
        )
    # Unlink calendar references so no orphan links remain.
    for event in db.scalars(
        select(CalendarEvent).where(CalendarEvent.book_id == book.id)
    ).all():
        event.book_id = None
    title = book.title
    db.delete(book)
    db.commit()
    logger.info("Hard-deleted book id=%s (%s)", book_id, title)
    return {
        "deleted": True,
        "message": f"'{title}' was permanently deleted.",
        "book": None,
    }
