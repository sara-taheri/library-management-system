"""FastAPI application factory.

Run locally with:
    uvicorn app.main:app --reload

`create_app()` accepts an optional database URL so the test-suite can
spin up isolated instances against throwaway SQLite files.
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
from app.web import STATIC_DIR, render

logger = logging.getLogger("app")

DEFAULT_DEV_SECRET = "dev-insecure-change-me"

ERROR_TITLES = {
    401: "Not signed in",
    403: "Access denied",
    404: "Page not found",
    405: "Method not allowed",
}


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


def create_app(database_url: str | None = None) -> FastAPI:
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

    @app.exception_handler(StarletteHTTPException)
    def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> Response:
        """JSON errors for API clients, friendly HTML pages for browsers."""
        accepts_json = request.url.path.startswith("/api") or "application/json" in (
            request.headers.get("accept") or ""
        )
        if accepts_json:
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

    return app


# Module-level instance used by `uvicorn app.main:app`.
app = create_app()
