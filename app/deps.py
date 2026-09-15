"""Shared FastAPI dependencies (database session + authentication guards)."""
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.models import User
from app.utils.sessions import session_user_id


def get_db(request: Request) -> Iterator[Session]:
    """Yield a database session bound to the current application."""
    session_factory = request.app.state.session_factory
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    """Return the session's user, or None when unauthenticated.

    Use on pages/endpoints that adapt to both states. Stale sessions
    (user deleted) are cleared and treated as logged-out.
    """
    user_id = session_user_id(request)
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None:
        request.session.clear()
    return user


def require_user(current_user: User | None = Depends(get_current_user)) -> User:
    """Guard for endpoints that demand an authenticated user (401 otherwise)."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return current_user


def require_admin(current_user: User = Depends(require_user)) -> User:
    """Guard for admin-only endpoints (403 for authenticated non-admins)."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return current_user
