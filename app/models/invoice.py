"""
Invoice model for Stripe billing.
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.subscription import Subscription


class Invoice(Base, UUIDMixin, TimestampMixin):
    """Stripe invoice record."""

    __tablename__ = "invoices"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stripe_invoice_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )
    amount: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(10),
        default="usd",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    pdf_url: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
    )

    # Relationships
    subscription: Mapped["Subscription"] = relationship(
        "Subscription",
        back_populates="invoices",
    )

    def __repr__(self) -> str:
        return f"<Invoice(id={self.id}, stripe_invoice_id={self.stripe_invoice_id}, amount={self.amount})>"
