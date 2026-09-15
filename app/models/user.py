"""User account model (evolves the legacy `model.User`)."""
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, utcnow

if TYPE_CHECKING:
    from app.models.event import CalendarEvent
    from app.models.loan import Loan

ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    # "bcrypt" for new/updated accounts. Rows migrated from the legacy
    # users.json keep "legacy_sha256" and are transparently upgraded to
    # bcrypt on their next successful login (Phase 3).
    hash_algorithm: Mapped[str] = mapped_column(String(20), default="bcrypt")

    role: Mapped[str] = mapped_column(String(20), default=ROLE_MEMBER, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    loans: Mapped[list["Loan"]] = relationship(back_populates="user")
    created_events: Mapped[list["CalendarEvent"]] = relationship(
        back_populates="creator"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.username!r} role={self.role!r}>"
