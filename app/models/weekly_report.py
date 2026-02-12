"""
Weekly report model for storing generated analytics reports.
"""
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Dict, List, Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class WeeklyReport(Base, UUIDMixin):
    """Weekly analytics report model."""

    __tablename__ = "weekly_reports"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    week_start: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    week_end: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    # Statistics
    total_reviews: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    sentiment_breakdown: Mapped[Optional[Dict]] = mapped_column(
        JSON,
        nullable=True,
    )
    top_problems: Mapped[Optional[List[Dict]]] = mapped_column(
        JSON,
        nullable=True,
    )
    critical_reviews: Mapped[Optional[List[str]]] = mapped_column(
        JSON,
        nullable=True,
    )

    # Comparison with previous week
    total_change_percent: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    sentiment_change: Mapped[Optional[Dict]] = mapped_column(
        JSON,
        nullable=True,
    )

    # AI recommendations
    recommendations: Mapped[Optional[List[str]]] = mapped_column(
        JSON,
        nullable=True,
    )

    # Delivery
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    pdf_url: Mapped[Optional[str]] = mapped_column(
        String(1000),
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
        back_populates="weekly_reports",
    )

    __table_args__ = (
        Index(
            "ix_weekly_reports_user_week",
            "user_id",
            "week_start",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<WeeklyReport(id={self.id}, user_id={self.user_id}, week={self.week_start})>"
