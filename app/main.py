"""FastAPI application factory.

Run locally with:
    uvicorn app.main:app --reload

`create_app()` accepts an optional database URL so the test-suite can
spin up isolated instances against throwaway SQLite files.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.config import settings
from app.database import Base, make_engine, make_session_factory
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app.routers import books as books_router

logger = logging.getLogger("app")

DEFAULT_DEV_SECRET = "dev-insecure-change-me"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "%s v%s starting (environment=%s)",
        settings.app_name,
        __version__,
        settings.environment,
    )
    # Phase 7+: the calendar runner (background worker processing due-date
    # events and reminders) will be started here and cancelled on shutdown.
    # It can open its own sessions via app.state.session_factory.
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
            "Phase 3 - authentication foundation: registration, login/logout "
            "with signed session cookies, bcrypt hashing (legacy SHA-256 "
            "accounts upgrade on login), and RBAC guards."
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

    app.include_router(books_router.router)
    app.include_router(auth_router.router)
    app.include_router(admin_router.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": __version__,
            "environment": settings.environment,
        }

    @app.get("/", tags=["meta"])
    def root() -> dict:
        return {
            "message": f"{settings.app_name} - API foundation (Phase 3)",
            "endpoints": {
                "health": "/health",
                "interactive_docs": "/docs",
                "books": "/api/books",
                "auth": "/api/auth/me",
            },
        }

    return app


# Module-level instance used by `uvicorn app.main:app`.
app = create_app()
