"""Admin API - every route requires an authenticated admin (403 otherwise).

Phase 3 provides the library overview (counts). Member management and
moderation tools arrive in Phase 6 on this router.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db, require_admin
from app.schemas.admin import AdminOverview
from app.services.stats_service import library_overview

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/overview", response_model=AdminOverview)
def overview(db: Session = Depends(get_db)):
    return AdminOverview(**library_overview(db))
