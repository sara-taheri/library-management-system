"""Shared pytest fixtures.

Every test gets an isolated application instance backed by a throwaway
SQLite file in pytest's tmp_path - tests never touch `data/library.db`
or the legacy JSON files.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Book


@pytest.fixture()
def app(tmp_path):
    db_file = tmp_path / "test_library.db"
    application = create_app(database_url=f"sqlite:///{db_file}")
    yield application
    application.state.engine.dispose()


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def seeded_app(app):
    """App pre-loaded with a small catalog (mirrors the legacy books.json)."""
    session_factory = app.state.session_factory
    with session_factory() as db:
        db.add_all(
            [
                Book(
                    id=1,
                    title="Harry Potter",
                    author="J.K. Rowling",
                    genre="Fantasy",
                    total_copies=5,
                    available_copies=4,
                ),
                Book(
                    id=2,
                    title="The Notebook",
                    author="Nicholas Sparks",
                    genre="Romance",
                    total_copies=4,
                    available_copies=4,
                ),
                Book(
                    id=3,
                    title="Hamlet",
                    author="William Shakespeare",
                    genre="Drama",
                    total_copies=7,
                    available_copies=7,
                ),
            ]
        )
        db.commit()
    return app


@pytest.fixture()
def seeded_client(seeded_app):
    with TestClient(seeded_app) as test_client:
        yield test_client
