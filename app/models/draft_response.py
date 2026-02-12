"""
DraftResponse model for AI-generated response drafts.
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin
from app.models.enums import ResponseTone

if TYPE_CHECKING:
    from app.models.review import Review


class DraftResponse(Base, UUIDMixin):
    """AI-generated draft response model."""

    __tablename__ = "draft_responses"

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    tone: Mapped[ResponseTone] = mapped_column(
        Text,
        nullable=False,
    )
    variant_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    review: Mapped["Review"] = relationship(
        "Review",
        back_populates="draft_responses",
    )

    def __repr__(self) -> str:
        return f"<DraftResponse(id={self.id}, review_id={self.review_id}, variant={self.variant_number})>"
