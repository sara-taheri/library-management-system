"""Pydantic schemas (request/response validation) for the HTTP API."""
from app.schemas.book import BookListResponse, BookOut

__all__ = ["BookListResponse", "BookOut"]
