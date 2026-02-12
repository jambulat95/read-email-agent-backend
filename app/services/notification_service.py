"""
Main notification service that orchestrates all notification channels.

Handles:
- Checking user notification settings
- Enforcing plan-based channel restrictions
- Sending notifications through enabled channels
"""
import logging
from dataclasses import dataclass
from typing import List, Optional

from app.config import get_settings
from app.models.enums import PlanType, PriorityType
from app.models.notification_settings import NotificationSettings
from app.models.review import Review
from app.models.user import User
from app.services.notifications.base import (
    Notification,
    NotificationChannel,
    NotificationResult,
)
from app.services.notifications.email import get_email_channel
from app.services.notifications.telegram import get_telegram_channel
from app.services.notifications.sms import get_sms_channel

logger = logging.getLogger(__name__)
settings = get_settings()


# Plan-based channel access
PLAN_CHANNELS = {
    PlanType.FREE: ["email"],
    PlanType.STARTER: ["email", "telegram"],
    PlanType.PROFESSIONAL: ["email", "telegram", "sms"],
    PlanType.ENTERPRISE: ["email", "telegram", "sms"],
}


@dataclass
class NotificationSummary:
    """Summary of notification results across all channels."""
    review_id: str
    total_channels: int
    successful: int
    failed: int
    results: List[NotificationResult]

    @property
    def all_successful(self) -> bool:
        return self.successful == self.total_channels and self.total_channels > 0

    @property
    def any_successful(self) -> bool:
        return self.successful > 0


class NotificationService:
    """
    Service for sending notifications about reviews.

    Supports multiple channels with plan-based restrictions:
    - FREE: Email only
    - STARTER: Email + Telegram
    - PRO/ENTERPRISE: Email + Telegram + SMS
    """

    def __init__(self):
        """Initialize notification channels."""
        self._email = get_email_channel()
        self._telegram = get_telegram_channel()
        self._sms = get_sms_channel()

        self._channels = {
            "email": self._email,
            "telegram": self._telegram,
            "sms": self._sms,
        }

    def get_available_channels(self, user: User) -> List[str]:
        """
        Get list of notification channels available for user's plan.

        Args:
            user: User to check

        Returns:
            List of channel names
        """
        plan = PlanType(user.plan) if isinstance(user.plan, str) else user.plan
        return PLAN_CHANNELS.get(plan, ["email"])

    def get_enabled_channels(
        self, user: User, notification_settings: Optional[NotificationSettings] = None
    ) -> List[NotificationChannel]:
        """
        Get list of enabled and available notification channels for user.

        Args:
            user: User to check
            notification_settings: User's notification settings (optional)

        Returns:
            List of NotificationChannel instances
        """
        if notification_settings is None:
            notification_settings = user.notification_settings

        if not notification_settings:
            # Default to email only
            return [self._email] if self._email.is_configured() else []

        available = self.get_available_channels(user)
        enabled = []

        # Check email
        if "email" in available and notification_settings.email_enabled:
            if self._email.is_configured():
                enabled.append(self._email)

        # Check telegram
        if "telegram" in available and notification_settings.telegram_enabled:
            if notification_settings.telegram_chat_id and self._telegram.is_configured():
                enabled.append(self._telegram)

        # Check SMS
        if "sms" in available and notification_settings.sms_enabled:
            if notification_settings.phone_number and self._sms.is_configured():
                enabled.append(self._sms)

        return enabled

    def should_notify(
        self,
        priority: PriorityType,
        notification_settings: Optional[NotificationSettings],
    ) -> bool:
        """
        Check if notification should be sent based on priority and settings.

        Args:
            priority: Review priority level
            notification_settings: User's notification settings

        Returns:
            True if notification should be sent
        """
        if notification_settings is None:
            # Default behavior: notify on critical and important
            return priority in (PriorityType.CRITICAL, PriorityType.IMPORTANT)

        priority_str = priority.value if isinstance(priority, PriorityType) else priority

        if priority_str == PriorityType.CRITICAL.value:
            return notification_settings.notify_on_critical
        elif priority_str == PriorityType.IMPORTANT.value:
            return notification_settings.notify_on_important
        elif priority_str == PriorityType.NORMAL.value:
            return notification_settings.notify_on_normal

        return False

    def build_notification(self, review: Review) -> Notification:
        """
        Build Notification object from Review.

        Args:
            review: Review to build notification for

        Returns:
            Notification instance
        """
        # Build dashboard URL
        dashboard_url = f"{settings.dashboard_url}/reviews/{review.id}"

        # Build email URL (Gmail deep link)
        email_url = None
        if review.message_id:
            # Gmail URL format for opening specific message
            email_url = f"https://mail.google.com/mail/u/0/#search/rfc822msgid:{review.message_id}"

        return Notification(
            review_id=review.id,
            priority=review.priority.value if review.priority else "normal",
            summary=review.summary or "",
            problems=review.problems or [],
            sender_email=review.sender_email,
            sender_name=review.sender_name,
            subject=review.subject,
            dashboard_url=dashboard_url,
            email_url=email_url,
        )

    async def send_review_notification(
        self, review: Review, user: User
    ) -> NotificationSummary:
        """
        Send notification about a review to user.

        Steps:
        1. Check if notification is needed based on priority
        2. Get enabled channels for user
        3. Send through all enabled channels
        4. Return summary of results

        Args:
            review: Review to notify about
            user: User to notify

        Returns:
            NotificationSummary with results
        """
        results: List[NotificationResult] = []

        # 1. Check if we should notify
        priority = PriorityType(review.priority) if review.priority else PriorityType.NORMAL
        if not self.should_notify(priority, user.notification_settings):
            logger.info(
                f"Skipping notification for review {review.id}: "
                f"priority {priority.value} not enabled"
            )
            return NotificationSummary(
                review_id=str(review.id),
                total_channels=0,
                successful=0,
                failed=0,
                results=[],
            )

        # 2. Get enabled channels
        channels = self.get_enabled_channels(user)
        if not channels:
            logger.warning(f"No enabled notification channels for user {user.id}")
            return NotificationSummary(
                review_id=str(review.id),
                total_channels=0,
                successful=0,
                failed=0,
                results=[],
            )

        # 3. Build notification
        notification = self.build_notification(review)

        # 4. Send through all channels
        for channel in channels:
            try:
                result = await channel.send(user, notification)
                results.append(result)

                if result.success:
                    logger.info(
                        f"Notification sent via {channel.channel_name} "
                        f"for review {review.id}"
                    )
                else:
                    logger.warning(
                        f"Failed to send via {channel.channel_name}: {result.error}"
                    )

            except Exception as e:
                logger.error(
                    f"Error sending via {channel.channel_name}: {e}"
                )
                results.append(
                    NotificationResult(
                        success=False,
                        channel=channel.channel_name,
                        error=str(e),
                    )
                )

        # 5. Build summary
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful

        return NotificationSummary(
            review_id=str(review.id),
            total_channels=len(channels),
            successful=successful,
            failed=failed,
            results=results,
        )

    async def send_account_alert(
        self, user: User, subject: str, message: str
    ) -> NotificationSummary:
        """
        Send account alert to user (e.g., OAuth error, quota exceeded).

        Only sends via email channel.

        Args:
            user: User to notify
            subject: Alert subject
            message: Alert message

        Returns:
            NotificationSummary with results
        """
        # Create a special notification for alerts
        from uuid import uuid4

        notification = Notification(
            review_id=uuid4(),  # Placeholder ID
            priority="important",
            summary=message,
            problems=[],
            sender_email="system@emailagent.com",
            sender_name="Email Agent System",
            subject=subject,
            dashboard_url=f"{settings.dashboard_url}/settings",
        )

        results = []

        # Only send via email for account alerts
        if self._email.is_configured():
            try:
                result = await self._email.send(user, notification)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to send account alert: {e}")
                results.append(
                    NotificationResult(
                        success=False,
                        channel="email",
                        error=str(e),
                    )
                )

        successful = sum(1 for r in results if r.success)

        return NotificationSummary(
            review_id=str(notification.review_id),
            total_channels=len(results),
            successful=successful,
            failed=len(results) - successful,
            results=results,
        )


# Singleton instance
_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Get singleton notification service."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service
