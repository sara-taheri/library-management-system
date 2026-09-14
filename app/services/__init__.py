"""Business-logic services.

Services are framework-free (no FastAPI/Starlette imports): they take a
SQLAlchemy session plus plain arguments and return models or raise
domain errors. This keeps them reusable from the HTTP layer, the CLI and
future background workers (e.g. the Phase 7+ calendar runner).
"""
