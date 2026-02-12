"""
Base notification interface and data structures.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
from uuid import UUID

from app.models.user import User


@dataclass
class Notification:
    """
    Notification data structure for review alerts.

    Contains all information needed to send a notification
    through any channel (email, telegram, sms).
    """
    review_id: UUID
    priority: str  # critical, important, normal
    summary: str
    problems: List[str] = field(default_factory=list)
    sender_email: str = ""
    sender_name: Optional[str] = None
    subject: str = ""
    dashboard_url: str = ""
    email_url: Optional[str] = None  # Direct link to email in Gmail

    @property
    def priority_emoji(self) -> str:
        """Return emoji for priority level."""
        return {
            "critical": "🚨",
            "important": "⚠️",
            "normal": "📧",
        }.get(self.priority, "📧")

    @property
    def priority_label(self) -> str:
        """Return human-readable priority label in Russian."""
        return {
            "critical": "Критический",
            "important": "Важный",
            "normal": "Обычный",
        }.get(self.priority, "Обычный")


@dataclass
class NotificationResult:
    """Result of sending a notification."""
    success: bool
    channel: str  # email, telegram, sms
    error: Optional[str] = None
    message_id: Optional[str] = None


class NotificationChannel(ABC):
    """
    Abstract base class for notification channels.

    Implementations:
    - EmailNotificationChannel (SendGrid)
    - TelegramNotificationChannel (Telegram Bot API)
    - SMSNotificationChannel (Twilio)
    """

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Return channel identifier."""
        pass

    @abstractmethod
    async def send(self, user: User, notification: Notification) -> NotificationResult:
        """
        Send notification to user.

        Args:
            user: User to notify
            notification: Notification data

        Returns:
            NotificationResult with success status
        """
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """
        Check if channel is properly configured.

        Returns:
            True if all required settings are present
        """
        pass
