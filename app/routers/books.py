"""Books API - Phase 2 is read-only.

Endpoints:
    GET /api/books        list/search/filter/paginate the catalog
    GET /api/books/{id}   book details

Write endpoints (admin create/update/delete) are added in Phase 4 on top
of this router.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Book
from app.schemas.book import BookListResponse, BookOut

router = APIRouter(prefix="/api/books", tags=["books"])


@router.get("", response_model=BookListResponse)
def list_books(
    db: Session = Depends(get_db),
    q: str | None = Query(
        None, description="Case-insensitive search in title and author"
    ),
    genre: str | None = Query(None, description="Exact genre filter (case-insensitive)"),
    available_only: bool = Query(False, description="Only books with free copies"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> BookListResponse:
    stmt = select(Book)

    if q and q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(Book.title.ilike(pattern), Book.author.ilike(pattern)))
    if genre and genre.strip():
        stmt = stmt.where(func.lower(Book.genre) == genre.strip().lower())
    if available_only:
        stmt = stmt.where(Book.available_copies > 0)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Book.title, Book.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return BookListResponse(
        items=[BookOut.model_validate(book) for book in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, -(-total // page_size)),  # ceil division
    )


@router.get("/{book_id}", response_model=BookOut)
def get_book(book_id: int, db: Session = Depends(get_db)) -> Book:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        )
    return book
