"""Session helpers.

The session itself is Starlette's signed cookie (see SessionMiddleware
wiring in app.main): tamper-proof, HttpOnly, SameSite=Lax, and Secure
in production. These helpers keep the key names in one place.
"""
from starlette.requests import Request

from app.models import User

USER_ID_KEY = "user_id"


def login_session(request: Request, user: User) -> None:
    """Attach an authenticated user to the session.

    The session is cleared first to mitigate session-fixation attacks
    (any pre-login cookie contents are discarded).
    """
    request.session.clear()
    request.session[USER_ID_KEY] = user.id


def logout_session(request: Request) -> None:
    request.session.clear()


def session_user_id(request: Request) -> int | None:
    return request.session.get(USER_ID_KEY)
