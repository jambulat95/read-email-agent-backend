"""
EmailAccount model for connected email accounts.
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.review import Review
    from app.models.user import User


class EmailAccount(Base, UUIDMixin):
    """Connected email account model."""

    __tablename__ = "email_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,  # gmail, outlook, etc.
    )
    oauth_token: Mapped[Optional[str]] = mapped_column(
        String(2000),  # Encrypted token
        nullable=True,
    )
    oauth_refresh_token: Mapped[Optional[str]] = mapped_column(
        String(2000),  # Encrypted refresh token
        nullable=True,
    )
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    check_interval_minutes: Mapped[int] = mapped_column(
        Integer,
        default=15,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="email_accounts",
    )
    reviews: Mapped[List["Review"]] = relationship(
        "Review",
        back_populates="email_account",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<EmailAccount(id={self.id}, email={self.email}, provider={self.provider})>"
