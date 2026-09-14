"""Application configuration.

Settings are read from environment variables and an optional `.env` file
at the repository root (see `.env.example`). Everything has a safe
development default so the app runs with zero configuration.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root (the folder that contains `app/`, `scripts/`, `tests/`).
BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_DB_PATH = (BASE_DIR / "data" / "library.db").as_posix()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Library Management System"
    environment: str = "development"  # development | production

    # Used to sign session cookies (Starlette SessionMiddleware).
    secret_key: str = "dev-insecure-change-me"

    # Session cookie settings.
    session_cookie_name: str = "lms_session"
    session_max_age_days: int = 7

    # SQLAlchemy database URL. Default: SQLite file under <repo>/data/.
    database_url: str = f"sqlite:///{DEFAULT_DB_PATH}"

    # Default borrowing window; due_at = borrowed_at + loan_period_days.
    loan_period_days: int = 14


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
