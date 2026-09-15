"""Loans API (Checkpoint 2: borrowing and returning).

Endpoints:
    POST /api/loans                 borrow a book          (any signed-in user)
    POST /api/loans/{id}/return     return a book          (owner or admin)
    GET  /api/loans/me              my loans + history     (signed-in)
    GET  /api/loans                 all loans              (admin)
    GET  /api/loans/{id}            one loan               (owner or admin)

Business rules live in app.services.loan_service - the same service the
server-rendered pages call, so API and UI can never drift apart.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.deps import get_db, require_admin, require_user
from app.models import Loan, User
from app.schemas.loan import BorrowRequest, LoanListResponse, LoanOut
from app.services import loan_service
from app.services.loan_service import LoanError

router = APIRouter(prefix="/api/loans", tags=["loans"])

STATUS_PATTERN = "^(active|returned)$"


def _raise_loan_error(exc: LoanError):
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("", response_model=LoanOut, status_code=201)
def borrow_book(
    payload: BorrowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
) -> Loan:
    try:
        return loan_service.borrow_book(db, user=current_user, book_id=payload.book_id)
    except LoanError as exc:
        _raise_loan_error(exc)


@router.post("/{loan_id}/return", response_model=LoanOut)
def return_loan(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
) -> Loan:
    try:
        return loan_service.return_book(db, loan_id=loan_id, actor=current_user)
    except LoanError as exc:
        _raise_loan_error(exc)


@router.get("/me", response_model=LoanListResponse)
def my_loans(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    status_filter: str | None = Query(None, alias="status", pattern=STATUS_PATTERN),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> LoanListResponse:
    items, total, pages = loan_service.list_loans(
        db,
        user_id=current_user.id,
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    return LoanListResponse(
        items=[LoanOut.model_validate(loan) for loan in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("", response_model=LoanListResponse, dependencies=[Depends(require_admin)])
def all_loans(
    db: Session = Depends(get_db),
    user_id: int | None = Query(None, description="Filter by member"),
    status_filter: str | None = Query(None, alias="status", pattern=STATUS_PATTERN),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> LoanListResponse:
    items, total, pages = loan_service.list_loans(
        db,
        user_id=user_id,
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    return LoanListResponse(
        items=[LoanOut.model_validate(loan) for loan in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/{loan_id}", response_model=LoanOut)
def loan_detail(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
) -> Loan:
    loan = loan_service.get_loan(db, loan_id)
    if loan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Loan not found"
        )
    if not (current_user.is_admin or loan.user_id == current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own loans",
        )
    return loan
