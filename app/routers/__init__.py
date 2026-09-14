"""HTTP routers (thin layer: validation in, service/db call, response out)."""
from app.routers import books

__all__ = ["books"]
