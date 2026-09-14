"""Minimal CSRF protection for cookie-authenticated HTML forms.

A random per-session token is embedded in every server-rendered form and
verified on POST (constant-time comparison).

The JSON API endpoints are deliberately not token-protected: browsers
cannot issue a cross-origin form POST with ``Content-Type:
application/json`` without a CORS preflight (which this app never
grants), and the session cookie is ``SameSite=Lax``.
"""
import hmac
import secrets

from starlette.requests import Request

CSRF_SESSION_KEY = "_csrf"
CSRF_FORM_FIELD = "_csrf"


def get_csrf_token(request: Request) -> str:
    """Return the session's CSRF token, creating one on first use."""
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def csrf_token_is_valid(request: Request, submitted: str | None) -> bool:
    expected = request.session.get(CSRF_SESSION_KEY, "")
    if not expected or not submitted:
        return False
    return hmac.compare_digest(expected, submitted)
