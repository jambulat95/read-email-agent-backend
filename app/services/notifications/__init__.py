"""
Notification services package.

Provides multi-channel notification support:
- Email via SendGrid
- Telegram via Bot API
- SMS via Twilio
"""
from app.services.notifications.base import (
    Notification,
    NotificationChannel,
    NotificationResult,
)
from app.services.notifications.email import EmailNotificationChannel
from app.services.notifications.telegram import (
    TelegramBotService,
    TelegramNotificationChannel,
)
from app.services.notifications.sms import SMSNotificationChannel

__all__ = [
    "Notification",
    "NotificationChannel",
    "NotificationResult",
    "EmailNotificationChannel",
    "TelegramNotificationChannel",
    "TelegramBotService",
    "SMSNotificationChannel",
]
