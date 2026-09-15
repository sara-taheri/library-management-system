"""One-shot flash messages carried in the signed session cookie.

Supports the Post/Redirect/Get pattern: a POST handler calls
:func:`flash`, redirects, and the next rendered page displays (and
consumes) the messages exactly once.
"""
from starlette.requests import Request

FLASH_SESSION_KEY = "_flashes"


def flash(request: Request, message: str, category: str = "info") -> None:
    """Queue a message. Category drives styling: info | success | error.

    The list is re-assigned at the top level on every call: Starlette's
    session only tracks top-level mutations, so appending in-place to an
    already-stored list would leave the session cookie unchanged and
    silently drop flashes queued between two page renders.
    """
    flashes = list(request.session.get(FLASH_SESSION_KEY, []))
    flashes.append({"message": message, "category": category})
    request.session[FLASH_SESSION_KEY] = flashes


def pop_flashes(request: Request) -> list[dict]:
    """Return and consume all queued messages (called once per render)."""
    return request.session.pop(FLASH_SESSION_KEY, [])
