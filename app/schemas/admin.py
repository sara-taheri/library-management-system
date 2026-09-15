"""Admin schemas."""
from pydantic import BaseModel


class AdminOverview(BaseModel):
    users: int
    books: int
    loans_total: int
    loans_active: int
    events: int
