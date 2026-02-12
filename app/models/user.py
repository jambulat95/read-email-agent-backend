"""
User model for application users.
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import PlanType

if TYPE_CHECKING:
    from app.models.company_settings import CompanySettings
    from app.models.email_account import EmailAccount
    from app.models.notification_settings import NotificationSettings
    from app.models.subscription import Subscription
    from app.models.weekly_report import WeeklyReport


class User(Base, UUIDMixin, TimestampMixin):
    """User account model."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )
    hashed_password: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,  # Nullable for OAuth users
    )
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    plan: Mapped[PlanType] = mapped_column(
        String(50),
        default=PlanType.FREE,
        nullable=False,
    )
    plan_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    email_accounts: Mapped[List["EmailAccount"]] = relationship(
        "EmailAccount",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    notification_settings: Mapped[Optional["NotificationSettings"]] = relationship(
        "NotificationSettings",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    company_settings: Mapped[Optional["CompanySettings"]] = relationship(
        "CompanySettings",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    weekly_reports: Mapped[List["WeeklyReport"]] = relationship(
        "WeeklyReport",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    subscription: Mapped[Optional["Subscription"]] = relationship(
        "Subscription",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email})>"
