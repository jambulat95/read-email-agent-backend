"""
SMS notification channel using Twilio.

Available only for Pro and Enterprise plans.
"""
import logging
from typing import Optional

from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException

from app.config import get_settings
from app.models.user import User
from app.services.notifications.base import (
    Notification,
    NotificationChannel,
    NotificationResult,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class SMSNotificationChannel(NotificationChannel):
    """
    SMS notification channel using Twilio API.

    Sends short notification messages about critical reviews.
    Available only for Pro and Enterprise plan users.
    """

    def __init__(self):
        """Initialize Twilio client."""
        self._client: Optional[TwilioClient] = None
        if self.is_configured():
            self._client = TwilioClient(
                settings.twilio_account_sid,
                settings.twilio_auth_token,
            )

    @property
    def channel_name(self) -> str:
        return "sms"

    def is_configured(self) -> bool:
        """Check if Twilio credentials are configured."""
        return bool(
            settings.twilio_account_sid
            and settings.twilio_auth_token
            and settings.twilio_phone_number
        )

    def _build_message(self, notification: Notification) -> str:
        """
        Build short SMS message.

        SMS has 160 character limit for single message,
        so we keep it very concise.
        """
        # Truncate summary to fit in SMS
        max_summary_len = 80
        summary = notification.summary
        if len(summary) > max_summary_len:
            summary = summary[: max_summary_len - 3] + "..."

        # Get short sender (email or name)
        sender = notification.sender_name or notification.sender_email
        if len(sender) > 25:
            sender = sender[:22] + "..."

        message = (
            f"[{notification.priority.upper()}] "
            f"Отзыв от {sender}\n"
            f"{summary}\n"
            f"Подробнее: {notification.dashboard_url}"
        )

        return message

    async def send(self, user: User, notification: Notification) -> NotificationResult:
        """
        Send SMS notification to user.

        Args:
            user: User to notify (needs notification_settings.phone_number)
            notification: Notification data

        Returns:
            NotificationResult with success status
        """
        if not self.is_configured():
            return NotificationResult(
                success=False,
                channel=self.channel_name,
                error="Twilio credentials not configured",
            )

        # Get phone number from user's notification settings
        if not user.notification_settings:
            return NotificationResult(
                success=False,
                channel=self.channel_name,
                error="User has no notification settings",
            )

        phone_number = user.notification_settings.phone_number
        if not phone_number:
            return NotificationResult(
                success=False,
                channel=self.channel_name,
                error="User has no phone number",
            )

        if not self._client:
            self._client = TwilioClient(
                settings.twilio_account_sid,
                settings.twilio_auth_token,
            )

        try:
            message_body = self._build_message(notification)

            message = self._client.messages.create(
                body=message_body,
                from_=settings.twilio_phone_number,
                to=phone_number,
            )

            logger.info(
                f"SMS notification sent to {phone_number} for review {notification.review_id}, "
                f"sid={message.sid}"
            )

            return NotificationResult(
                success=True,
                channel=self.channel_name,
                message_id=message.sid,
            )

        except TwilioRestException as e:
            logger.error(f"Twilio error for {phone_number}: {e}")
            return NotificationResult(
                success=False,
                channel=self.channel_name,
                error=f"Twilio error: {e.msg}",
            )
        except Exception as e:
            logger.error(f"Error sending SMS to {phone_number}: {e}")
            return NotificationResult(
                success=False,
                channel=self.channel_name,
                error=str(e),
            )


# Singleton instance
_sms_channel: Optional[SMSNotificationChannel] = None


def get_sms_channel() -> SMSNotificationChannel:
    """Get singleton SMS notification channel."""
    global _sms_channel
    if _sms_channel is None:
        _sms_channel = SMSNotificationChannel()
    return _sms_channel
