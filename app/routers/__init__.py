"""HTTP routers (thin layer: validation in, service/db call, response out)."""
from app.routers import admin, auth, books, pages

__all__ = ["admin", "auth", "books", "pages"]
