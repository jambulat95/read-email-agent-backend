"""
Review model for analyzed email reviews.
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin
from app.models.enums import PriorityType, SentimentType

if TYPE_CHECKING:
    from app.models.draft_response import DraftResponse
    from app.models.email_account import EmailAccount


class Review(Base, UUIDMixin):
    """Analyzed email review model."""

    __tablename__ = "reviews"

    email_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("email_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,  # Gmail/provider message ID
    )
    sender_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    sender_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    subject: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # AI Analysis fields
    sentiment: Mapped[Optional[SentimentType]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )
    priority: Mapped[Optional[PriorityType]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )
    summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    problems: Mapped[Optional[List[str]]] = mapped_column(
        JSON,
        nullable=True,
        default=list,
    )
    suggestions: Mapped[Optional[List[str]]] = mapped_column(
        JSON,
        nullable=True,
        default=list,
    )

    # Processing status
    is_processed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # User notes
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationships
    email_account: Mapped["EmailAccount"] = relationship(
        "EmailAccount",
        back_populates="reviews",
    )
    draft_responses: Mapped[List["DraftResponse"]] = relationship(
        "DraftResponse",
        back_populates="review",
        cascade="all, delete-orphan",
    )

    # Indexes
    __table_args__ = (
        Index(
            "ix_reviews_email_account_message",
            "email_account_id",
            "message_id",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<Review(id={self.id}, subject={self.subject[:50]}...)>"
