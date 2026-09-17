"""Server-rendered web layer: Jinja2 templates + a shared render helper.

`render()` injects the context every page needs (current user, CSRF
token, flash messages) so individual route handlers stay tiny.
"""
from pathlib import Path

from fastapi.requests import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.utils.csrf import get_csrf_token
from app.utils.flash import pop_flashes

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def nav_active(request: Request, href: str) -> bool:
    """True when the current path is `href` or a nested page under it.

    Home (`/`) is exact-match only so it does not light up on every URL.
    """
    path = request.url.path
    if href == "/":
        return path == "/"
    href = href.rstrip("/") or "/"
    return path == href or path.startswith(href + "/")


templates.env.globals["nav_active"] = nav_active


def render(
    request: Request,
    template_name: str,
    *,
    current_user=None,
    status_code: int = 200,
    **context,
) -> Response:
    base_context = {
        "request": request,
        "current_user": current_user,
        "csrf_token": get_csrf_token(request),
        "flashes": pop_flashes(request),
    }
    base_context.update(context)
    return templates.TemplateResponse(
        request, template_name, base_context, status_code=status_code
    )
