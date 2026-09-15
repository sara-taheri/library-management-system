"""Books API.

Endpoints (Checkpoint 1 - full management):
    GET    /api/books              list/search/filter/paginate (public)
    GET    /api/books/{id}         book details (public)
    POST   /api/books              create a book          (admin)
    PUT    /api/books/{id}         update a book          (admin)
    DELETE /api/books/{id}         deactivate (default) or
                                   permanently delete (?hard=true)  (admin)

All business rules live in app.services.book_service; this router only
translates HTTP <-> service calls.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.deps import get_db, require_admin
from app.models import Book
from app.schemas.book import (
    BookCreate,
    BookDeleteResponse,
    BookListResponse,
    BookOut,
    BookUpdate,
)
from app.services import book_service
from app.services.book_service import BookError

router = APIRouter(prefix="/api/books", tags=["books"])


def _raise_book_error(exc: BookError):
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("", response_model=BookListResponse)
def list_books(
    db: Session = Depends(get_db),
    q: str | None = Query(
        None, description="Case-insensitive search in title and author"
    ),
    genre: str | None = Query(None, description="Exact genre filter (case-insensitive)"),
    available_only: bool = Query(False, description="Only books with free copies"),
    include_inactive: bool = Query(
        False, description="Admin-oriented: also list deactivated books"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> BookListResponse:
    items, total, pages = book_service.list_books(
        db,
        q=q,
        genre=genre,
        available_only=available_only,
        include_inactive=include_inactive,
        page=page,
        page_size=page_size,
    )
    return BookListResponse(
        items=[BookOut.model_validate(book) for book in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/{book_id}", response_model=BookOut)
def get_book(book_id: int, db: Session = Depends(get_db)) -> Book:
    book = book_service.get_book(db, book_id)
    if book is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        )
    return book


@router.post(
    "",
    response_model=BookOut,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def create_book(payload: BookCreate, db: Session = Depends(get_db)) -> Book:
    try:
        return book_service.create_book(
            db,
            title=payload.title,
            author=payload.author,
            isbn=payload.isbn,
            genre=payload.genre,
            description=payload.description,
            total_copies=payload.total_copies,
        )
    except BookError as exc:
        _raise_book_error(exc)


@router.put(
    "/{book_id}",
    response_model=BookOut,
    dependencies=[Depends(require_admin)],
)
def update_book(
    book_id: int, payload: BookUpdate, db: Session = Depends(get_db)
) -> Book:
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update. Send at least one field.",
        )
    try:
        return book_service.update_book(db, book_id, fields)
    except BookError as exc:
        _raise_book_error(exc)


@router.delete(
    "/{book_id}",
    response_model=BookDeleteResponse,
    dependencies=[Depends(require_admin)],
)
def delete_book(
    book_id: int,
    db: Session = Depends(get_db),
    hard: bool = Query(
        False,
        description="false (default) = safe deactivate; true = permanent delete "
        "(only when no loan records reference the book)",
    ),
):
    try:
        result = book_service.delete_book(db, book_id, hard=hard)
    except BookError as exc:
        _raise_book_error(exc)
    return BookDeleteResponse(
        message=result["message"],
        deleted=result["deleted"],
        book=BookOut.model_validate(result["book"]) if result["book"] else None,
    )
