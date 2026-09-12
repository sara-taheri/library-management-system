"""Database engine / session setup (SQLAlchemy 2.0 style).

The engine is created per-application (see `app.main.create_app`) so tests
can point the app at a throwaway database. This module only provides the
declarative Base and small factory helpers.
"""
from datetime import datetime, timezone

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def utcnow() -> datetime:
    """Current time as *naive* UTC.

    SQLite does not persist tzinfo, so storing/returning naive UTC keeps
    every datetime in the app directly comparable.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_engine(database_url: str) -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite"):
        # FastAPI may serve requests from worker threads.
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
