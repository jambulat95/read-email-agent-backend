"""
Telegram notification channel using python-telegram-bot.
"""
import logging
import secrets
from typing import Optional

from telegram import Bot, Update
from telegram.error import TelegramError

from app.config import get_settings
from app.models.user import User
from app.services.notifications.base import (
    Notification,
    NotificationChannel,
    NotificationResult,
)
from app.services.redis_client import get_redis_client

logger = logging.getLogger(__name__)
settings = get_settings()

# Redis key prefix for telegram connection codes
TELEGRAM_CODE_PREFIX = "telegram_code:"
TELEGRAM_CODE_TTL = 600  # 10 minutes


class TelegramNotificationChannel(NotificationChannel):
    """
    Telegram notification channel using Bot API.

    Sends formatted messages about reviews that require attention.
    """

    def __init__(self):
        """Initialize Telegram bot."""
        self._bot: Optional[Bot] = None
        if self.is_configured():
            self._bot = Bot(token=settings.telegram_bot_token)

    @property
    def channel_name(self) -> str:
        return "telegram"

    def is_configured(self) -> bool:
        """Check if Telegram bot token is configured."""
        return bool(settings.telegram_bot_token)

    def _build_message(self, notification: Notification) -> str:
        """Build Telegram message with Markdown formatting."""
        problems_text = ""
        if notification.problems:
            problems_list = "\n".join(f"  - {p}" for p in notification.problems[:5])
            if len(notification.problems) > 5:
                problems_list += f"\n  ... и ещё {len(notification.problems) - 5}"
            problems_text = f"\n\n*Выявленные проблемы:*\n{problems_list}"

        sender = notification.sender_name or notification.sender_email

        message = f"""
{notification.priority_emoji} *Новый отзыв требует внимания*

*Приоритет:* {notification.priority_label}
*Отправитель:* {sender}
*Тема:* {notification.subject}

*Краткое содержание:*
{notification.summary}
{problems_text}

[Открыть в дашборде]({notification.dashboard_url})
        """.strip()

        return message

    async def send(self, user: User, notification: Notification) -> NotificationResult:
        """
        Send Telegram notification to user.

        Args:
            user: User to notify (needs notification_settings.telegram_chat_id)
            notification: Notification data

        Returns:
            NotificationResult with success status
        """
        if not self.is_configured():
            return NotificationResult(
                success=False,
                channel=self.channel_name,
                error="Telegram bot token not configured",
            )

        # Get chat_id from user's notification settings
        if not user.notification_settings:
            return NotificationResult(
                success=False,
                channel=self.channel_name,
                error="User has no notification settings",
            )

        chat_id = user.notification_settings.telegram_chat_id
        if not chat_id:
            return NotificationResult(
                success=False,
                channel=self.channel_name,
                error="User has no Telegram chat ID",
            )

        if not self._bot:
            self._bot = Bot(token=settings.telegram_bot_token)

        try:
            message = self._build_message(notification)

            result = await self._bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )

            logger.info(
                f"Telegram notification sent to chat {chat_id} for review {notification.review_id}"
            )

            return NotificationResult(
                success=True,
                channel=self.channel_name,
                message_id=str(result.message_id),
            )

        except TelegramError as e:
            logger.error(f"Telegram error for chat {chat_id}: {e}")
            return NotificationResult(
                success=False,
                channel=self.channel_name,
                error=str(e),
            )
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return NotificationResult(
                success=False,
                channel=self.channel_name,
                error=str(e),
            )


class TelegramBotService:
    """
    Service for managing Telegram bot connections.

    Handles:
    - Generating connection codes
    - Processing webhook updates
    - Linking users to chat IDs
    """

    def __init__(self):
        """Initialize Telegram bot service."""
        self._bot: Optional[Bot] = None
        if self.is_configured():
            self._bot = Bot(token=settings.telegram_bot_token)

    def is_configured(self) -> bool:
        """Check if Telegram bot token is configured."""
        return bool(settings.telegram_bot_token)

    async def set_webhook(self, url: str) -> bool:
        """
        Set webhook URL for Telegram updates.

        Args:
            url: Webhook URL (e.g., https://yourdomain.com/api/telegram/webhook)

        Returns:
            True if webhook was set successfully
        """
        if not self.is_configured() or not self._bot:
            return False

        try:
            await self._bot.set_webhook(url)
            logger.info(f"Telegram webhook set to {url}")
            return True
        except TelegramError as e:
            logger.error(f"Failed to set webhook: {e}")
            return False

    async def delete_webhook(self) -> bool:
        """Delete webhook for polling mode."""
        if not self.is_configured() or not self._bot:
            return False

        try:
            await self._bot.delete_webhook()
            logger.info("Telegram webhook deleted")
            return True
        except TelegramError as e:
            logger.error(f"Failed to delete webhook: {e}")
            return False

    async def generate_connection_code(self, user_id: str) -> str:
        """
        Generate a unique code for linking Telegram account.

        Args:
            user_id: User ID to associate with the code

        Returns:
            6-character connection code
        """
        code = secrets.token_hex(3).upper()  # 6 character hex code

        # Store in Redis with user_id
        redis = await get_redis_client()
        key = f"{TELEGRAM_CODE_PREFIX}{code}"
        await redis.setex(key, TELEGRAM_CODE_TTL, user_id)

        logger.info(f"Generated Telegram connection code for user {user_id}")
        return code

    async def get_user_id_by_code(self, code: str) -> Optional[str]:
        """
        Get user ID associated with a connection code.

        Args:
            code: Connection code from /start command

        Returns:
            User ID if code is valid, None otherwise
        """
        redis = await get_redis_client()
        key = f"{TELEGRAM_CODE_PREFIX}{code.upper()}"

        user_id = await redis.get(key)
        if user_id:
            # Delete code after use (one-time use)
            await redis.delete(key)
            return user_id.decode() if isinstance(user_id, bytes) else user_id

        return None

    async def handle_update(self, update_data: dict) -> Optional[dict]:
        """
        Process incoming Telegram webhook update.

        Handles /start command for account linking.

        Args:
            update_data: Raw update data from Telegram

        Returns:
            Response dict with action taken, or None
        """
        try:
            update = Update.de_json(update_data, self._bot)

            if not update or not update.message:
                return None

            message = update.message
            chat_id = message.chat_id
            text = message.text or ""

            # Handle /start command with connection code
            if text.startswith("/start"):
                parts = text.split(maxsplit=1)
                if len(parts) == 2:
                    code = parts[1].strip()
                    user_id = await self.get_user_id_by_code(code)

                    if user_id:
                        logger.info(
                            f"Telegram linked: user {user_id} -> chat {chat_id}"
                        )

                        # Send confirmation message
                        if self._bot:
                            await self._bot.send_message(
                                chat_id=chat_id,
                                text=(
                                    "Telegram успешно подключён к вашему аккаунту "
                                    "Email Agent!\n\n"
                                    "Теперь вы будете получать уведомления о важных "
                                    "отзывах прямо в Telegram."
                                ),
                            )

                        return {
                            "action": "linked",
                            "user_id": user_id,
                            "chat_id": str(chat_id),
                        }
                    else:
                        # Invalid or expired code
                        if self._bot:
                            await self._bot.send_message(
                                chat_id=chat_id,
                                text=(
                                    "Код подключения недействителен или истёк.\n\n"
                                    "Пожалуйста, получите новый код в настройках "
                                    "Email Agent и попробуйте снова."
                                ),
                            )
                        return {"action": "invalid_code"}
                else:
                    # /start without code
                    if self._bot:
                        await self._bot.send_message(
                            chat_id=chat_id,
                            text=(
                                "Добро пожаловать в Email Agent Bot!\n\n"
                                "Чтобы подключить уведомления, перейдите в настройки "
                                "вашего аккаунта Email Agent и нажмите "
                                "\"Подключить Telegram\"."
                            ),
                        )
                    return {"action": "welcome"}

            # Handle other messages
            if self._bot:
                await self._bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "Я бот Email Agent для уведомлений.\n"
                        "Для подключения перейдите в настройки вашего аккаунта."
                    ),
                )

            return {"action": "unknown_command"}

        except Exception as e:
            logger.error(f"Error handling Telegram update: {e}")
            return {"action": "error", "error": str(e)}


# Singleton instances
_telegram_channel: Optional[TelegramNotificationChannel] = None
_telegram_bot_service: Optional[TelegramBotService] = None


def get_telegram_channel() -> TelegramNotificationChannel:
    """Get singleton Telegram notification channel."""
    global _telegram_channel
    if _telegram_channel is None:
        _telegram_channel = TelegramNotificationChannel()
    return _telegram_channel


def get_telegram_bot_service() -> TelegramBotService:
    """Get singleton Telegram bot service."""
    global _telegram_bot_service
    if _telegram_bot_service is None:
        _telegram_bot_service = TelegramBotService()
    return _telegram_bot_service
