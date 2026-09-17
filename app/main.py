"""FastAPI application factory.

Run locally with:
    uvicorn app.main:app --reload

`create_app()` accepts an optional database URL so the test-suite can
spin up isolated instances against throwaway SQLite files. Pass
`seed=True` to load sample books/demo users into an empty test DB;
the default is to seed only when using the configured DATABASE_URL.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from app import __version__
from app.config import settings
from app.database import Base, make_engine, make_session_factory
from app.models import User
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app.routers import books as books_router
from app.routers import events as events_router
from app.routers import loans as loans_router
from app.routers import pages as pages_router
from app.utils.sessions import session_user_id
from app.services.seed_service import seed_if_empty
from app.web import STATIC_DIR, render

logger = logging.getLogger("app")

DEFAULT_DEV_SECRET = "dev-insecure-change-me"

# Generic copy shown to clients on an unexpected failure. The real
# exception is logged server-side and must never appear in the response.
GENERIC_SERVER_ERROR = "An unexpected error occurred. Please try again later."

ERROR_TITLES = {
    401: "Not signed in",
    403: "Access denied",
    404: "Page not found",
    405: "Method not allowed",
    500: "Something went wrong",
}


def _wants_json(request: Request) -> bool:
    """API paths (and explicit JSON clients) get JSON errors, not HTML."""
    return request.url.path.startswith("/api") or "application/json" in (
        request.headers.get("accept") or ""
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "%s v%s starting (environment=%s)",
        settings.app_name,
        __version__,
        settings.environment,
    )
    # The calendar runner is deliberately NOT a background worker: it is a
    # one-shot service (app.services.runner_service) driven by
    # `python scripts/run_calendar_tasks.py` (manually or from cron).
    # That keeps the app a single simple process with no scheduler state.
    yield
    logger.info("%s shutting down", settings.app_name)


def create_app(database_url: str | None = None, seed: bool | None = None) -> FastAPI:
    if settings.environment == "production" and settings.secret_key == DEFAULT_DEV_SECRET:
        raise RuntimeError(
            "Refusing to start in production with the default SECRET_KEY. "
            "Set a strong SECRET_KEY in the environment or .env file."
        )

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        description=(
            "Library Management System - FastAPI + server-rendered pages. "
            "Authentication (bcrypt, transparent legacy SHA-256 upgrade, "
            "RBAC), book catalog management with safe delete, and "
            "borrowing/returning with due-date scheduling. JSON API under "
            "/api, HTML pages under /."
        ),
    )

    url = database_url or settings.database_url

    # Make sure the parent folder of a file-based SQLite database exists.
    if url.startswith("sqlite:///"):
        db_path = url.removeprefix("sqlite:///")
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = make_engine(url)
    # Pragmatic schema creation for development; migrations (Alembic) are a
    # later-phase concern once the schema stabilises.
    Base.metadata.create_all(engine)

    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    # First-boot sample data: only when the books/users tables are empty.
    # Tests pass database_url=... and default seed=False so they stay empty.
    # `uvicorn app.main:app` uses create_app() with no URL, so a fresh
    # data/library.db gets the catalog + bcrypt demo accounts once.
    if seed is None:
        seed = database_url is None
    if seed:
        with app.state.session_factory() as db:
            seed_if_empty(db)

    # Signed session cookie: HttpOnly + SameSite=Lax always; the Secure
    # flag is enabled in production (https_only) so local http:// works.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        max_age=settings.session_max_age_days * 24 * 3600,
        same_site="lax",
        https_only=settings.environment == "production",
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(books_router.router)
    app.include_router(loans_router.router)
    app.include_router(events_router.router)
    app.include_router(auth_router.router)
    app.include_router(admin_router.router)
    app.include_router(pages_router.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": __version__,
            "environment": settings.environment,
        }

    @app.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:
        """Lightweight browser hardening. Does not change response bodies."""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        return response

    @app.exception_handler(StarletteHTTPException)
    def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> Response:
        """JSON errors for API clients, friendly HTML pages for browsers."""
        if _wants_json(request):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=getattr(exc, "headers", None),
            )

        current_user = None
        user_id = session_user_id(request)
        if user_id is not None:
            with app.state.session_factory() as db:
                current_user = db.get(User, user_id)

        return render(
            request,
            "error.html",
            current_user=current_user,
            status_code=exc.status_code,
            error_code=exc.status_code,
            error_title=ERROR_TITLES.get(exc.status_code, "Something went wrong"),
            detail=exc.detail,
        )

    @app.exception_handler(Exception)
    def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        """Last-resort 500: log the traceback, never send it to the client.

        HTTPException / validation errors have more specific handlers and
        are not routed here. The error page is rendered without touching
        the database so a failed query cannot cascade into a second error.
        """
        logger.error(
            "Unhandled exception on %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
        if _wants_json(request):
            return JSONResponse(
                status_code=500, content={"detail": GENERIC_SERVER_ERROR}
            )
        return render(
            request,
            "error.html",
            current_user=None,
            status_code=500,
            error_code=500,
            error_title=ERROR_TITLES[500],
            detail=GENERIC_SERVER_ERROR,
        )

    return app


# Module-level instance used by `uvicorn app.main:app`.
app = create_app()
