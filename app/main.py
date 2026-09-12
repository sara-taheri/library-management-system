"""FastAPI application factory.

Run locally with:
    uvicorn app.main:app --reload

`create_app()` accepts an optional database URL so the test-suite can
spin up isolated instances against throwaway SQLite files.
"""
import logging
from pathlib import Path

from fastapi import FastAPI

from app import __version__
from app.config import settings
from app.database import Base, make_engine, make_session_factory
from app.routers import books as books_router

logger = logging.getLogger("app")


def create_app(database_url: str | None = None) -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Phase 2 - API foundation (health check + read-only books API). "
            "Authentication, dashboards, calendar and UI pages follow in the "
            "next phases."
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

    app.include_router(books_router.router)

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
            "message": f"{settings.app_name} - API foundation (Phase 2)",
            "endpoints": {
                "health": "/health",
                "interactive_docs": "/docs",
                "books": "/api/books",
                "book_detail_example": "/api/books/1",
            },
        }

    logger.info("Created %s (db=%s)", settings.app_name, url)
    return app


# Module-level instance used by `uvicorn app.main:app`.
app = create_app()
