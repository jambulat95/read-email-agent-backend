"""
Email notification channel using SendGrid.
"""
import logging
from typing import Optional

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Content, To

from app.config import get_settings
from app.models.user import User
from app.services.notifications.base import (
    Notification,
    NotificationChannel,
    NotificationResult,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class EmailNotificationChannel(NotificationChannel):
    """
    Email notification channel using SendGrid API.

    Sends HTML-formatted notification emails about
    new reviews that require attention.
    """

    def __init__(self):
        """Initialize SendGrid client."""
        self._client: Optional[SendGridAPIClient] = None
        if self.is_configured():
            self._client = SendGridAPIClient(settings.sendgrid_api_key)

    @property
    def channel_name(self) -> str:
        return "email"

    def is_configured(self) -> bool:
        """Check if SendGrid API key is configured."""
        return bool(settings.sendgrid_api_key)

    def _build_html_content(self, notification: Notification) -> str:
        """Build HTML email content."""
        problems_html = ""
        if notification.problems:
            problems_list = "".join(
                f"<li>{problem}</li>" for problem in notification.problems
            )
            problems_html = f"""
            <div style="background-color: #fff3cd; border-radius: 8px; padding: 16px; margin: 16px 0;">
                <h3 style="color: #856404; margin: 0 0 12px 0;">Выявленные проблемы:</h3>
                <ul style="color: #856404; margin: 0; padding-left: 20px;">
                    {problems_list}
                </ul>
            </div>
            """

        email_button = ""
        if notification.email_url:
            email_button = f"""
            <a href="{notification.email_url}"
               style="display: inline-block; background-color: #6c757d; color: white;
                      padding: 12px 24px; text-decoration: none; border-radius: 4px;
                      margin-left: 8px;">
                Открыть письмо
            </a>
            """

        priority_colors = {
            "critical": "#dc3545",
            "important": "#fd7e14",
            "normal": "#28a745",
        }
        priority_color = priority_colors.get(notification.priority, "#28a745")

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                     line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background-color: #f8f9fa; border-radius: 8px; padding: 24px;">
                <!-- Header -->
                <div style="border-bottom: 1px solid #dee2e6; padding-bottom: 16px; margin-bottom: 16px;">
                    <h1 style="margin: 0; color: #212529; font-size: 24px;">
                        {notification.priority_emoji} Новый отзыв требует внимания
                    </h1>
                </div>

                <!-- Priority Badge -->
                <div style="margin-bottom: 16px;">
                    <span style="background-color: {priority_color}; color: white;
                                 padding: 4px 12px; border-radius: 4px; font-size: 14px;
                                 font-weight: 600;">
                        Приоритет: {notification.priority_label}
                    </span>
                </div>

                <!-- Sender Info -->
                <div style="background-color: white; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                    <p style="margin: 0 0 8px 0;">
                        <strong>Отправитель:</strong>
                        {notification.sender_name or notification.sender_email}
                        {f'&lt;{notification.sender_email}&gt;' if notification.sender_name else ''}
                    </p>
                    <p style="margin: 0;">
                        <strong>Тема:</strong> {notification.subject}
                    </p>
                </div>

                <!-- Summary -->
                <div style="background-color: white; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                    <h3 style="margin: 0 0 12px 0; color: #495057;">Краткое содержание:</h3>
                    <p style="margin: 0; color: #6c757d;">{notification.summary}</p>
                </div>

                <!-- Problems -->
                {problems_html}

                <!-- Action Buttons -->
                <div style="text-align: center; margin-top: 24px;">
                    <a href="{notification.dashboard_url}"
                       style="display: inline-block; background-color: #0d6efd; color: white;
                              padding: 12px 24px; text-decoration: none; border-radius: 4px;">
                        Открыть в дашборде
                    </a>
                    {email_button}
                </div>

                <!-- Footer -->
                <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #dee2e6;
                            text-align: center; color: #6c757d; font-size: 12px;">
                    <p style="margin: 0;">
                        Это автоматическое уведомление от Email Agent.
                        <br>
                        Вы можете настроить уведомления в личном кабинете.
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        return html

    def _build_plain_text(self, notification: Notification) -> str:
        """Build plain text email content."""
        problems_text = ""
        if notification.problems:
            problems_list = "\n".join(f"  - {p}" for p in notification.problems)
            problems_text = f"\nВыявленные проблемы:\n{problems_list}\n"

        text = f"""
{notification.priority_emoji} Новый отзыв требует внимания

Приоритет: {notification.priority_label}

Отправитель: {notification.sender_name or notification.sender_email}
Тема: {notification.subject}

Краткое содержание:
{notification.summary}
{problems_text}
Открыть в дашборде: {notification.dashboard_url}
{f'Открыть письмо: {notification.email_url}' if notification.email_url else ''}

---
Это автоматическое уведомление от Email Agent.
        """.strip()
        return text

    async def send(self, user: User, notification: Notification) -> NotificationResult:
        """
        Send email notification to user.

        Args:
            user: User to notify (uses user.email)
            notification: Notification data

        Returns:
            NotificationResult with success status
        """
        if not self.is_configured():
            return NotificationResult(
                success=False,
                channel=self.channel_name,
                error="SendGrid API key not configured",
            )

        if not self._client:
            self._client = SendGridAPIClient(settings.sendgrid_api_key)

        try:
            subject = f"[{notification.priority_label}] Новый отзыв от {notification.sender_email}"

            message = Mail(
                from_email=settings.notification_from_email,
                to_emails=To(user.email),
                subject=subject,
            )

            # Add HTML content
            html_content = self._build_html_content(notification)
            message.add_content(Content("text/html", html_content))

            # Add plain text alternative
            plain_text = self._build_plain_text(notification)
            message.add_content(Content("text/plain", plain_text))

            response = self._client.send(message)

            if response.status_code in (200, 201, 202):
                logger.info(
                    f"Email notification sent to {user.email} for review {notification.review_id}"
                )
                return NotificationResult(
                    success=True,
                    channel=self.channel_name,
                    message_id=response.headers.get("X-Message-Id"),
                )
            else:
                logger.error(
                    f"Failed to send email to {user.email}: status={response.status_code}"
                )
                return NotificationResult(
                    success=False,
                    channel=self.channel_name,
                    error=f"SendGrid returned status {response.status_code}",
                )

        except Exception as e:
            logger.error(f"Error sending email to {user.email}: {e}")
            return NotificationResult(
                success=False,
                channel=self.channel_name,
                error=str(e),
            )


# Singleton instance
_email_channel: Optional[EmailNotificationChannel] = None


def get_email_channel() -> EmailNotificationChannel:
    """Get singleton email notification channel."""
    global _email_channel
    if _email_channel is None:
        _email_channel = EmailNotificationChannel()
    return _email_channel
