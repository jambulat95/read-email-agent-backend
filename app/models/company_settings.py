"""
CompanySettings model for user company preferences.
"""
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin
from app.models.enums import ResponseTone

if TYPE_CHECKING:
    from app.models.user import User


class CompanySettings(Base, UUIDMixin):
    """User company settings model."""

    __tablename__ = "company_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    company_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    industry: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    response_tone: Mapped[ResponseTone] = mapped_column(
        String(50),
        default=ResponseTone.PROFESSIONAL,
        nullable=False,
    )
    custom_instructions: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    custom_templates: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="company_settings",
    )

    def __repr__(self) -> str:
        return f"<CompanySettings(id={self.id}, user_id={self.user_id}, company={self.company_name})>"
