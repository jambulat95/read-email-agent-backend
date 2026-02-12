"""
API routes for Telegram bot integration.

Endpoints:
- POST /api/telegram/webhook - Handle Telegram updates
- GET /api/telegram/connect - Get connection code for linking account
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_async_session as get_db
from app.models.notification_settings import NotificationSettings
from app.models.user import User
from app.services.notifications.telegram import get_telegram_bot_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])


class TelegramConnectResponse(BaseModel):
    """Response for Telegram connection endpoint."""
    code: str
    bot_username: str
    deep_link: str
    expires_in_seconds: int = 600


class TelegramWebhookResponse(BaseModel):
    """Response for Telegram webhook endpoint."""
    ok: bool
    action: Optional[str] = None


@router.get("/connect", response_model=TelegramConnectResponse)
async def get_connection_code(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a code to connect Telegram account.

    The user should send this code to the bot via:
    1. Direct message: /start {code}
    2. Or via deep link: t.me/{bot_username}?start={code}

    Returns connection code that expires in 10 minutes.
    """
    bot_service = get_telegram_bot_service()

    if not bot_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot is not configured",
        )

    # Generate connection code
    code = await bot_service.generate_connection_code(str(current_user.id))

    # Get bot username from settings or use placeholder
    from app.config import get_settings
    settings = get_settings()

    # Try to get bot info (username)
    bot_username = "EmailAgentBot"  # Default placeholder
    if bot_service._bot:
        try:
            bot_info = await bot_service._bot.get_me()
            bot_username = bot_info.username
        except Exception as e:
            logger.warning(f"Could not get bot info: {e}")

    deep_link = f"https://t.me/{bot_username}?start={code}"

    return TelegramConnectResponse(
        code=code,
        bot_username=bot_username,
        deep_link=deep_link,
        expires_in_seconds=600,
    )


@router.post("/webhook", response_model=TelegramWebhookResponse)
async def telegram_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle Telegram webhook updates.

    This endpoint receives updates from Telegram when users
    interact with the bot.

    Main flow:
    1. User sends /start {code} to bot
    2. This endpoint receives the update
    3. We validate the code and link user's account
    4. Save telegram_chat_id to user's notification settings
    """
    bot_service = get_telegram_bot_service()

    if not bot_service.is_configured():
        # Return ok to avoid Telegram retries
        return TelegramWebhookResponse(ok=True, action="not_configured")

    try:
        update_data = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook data: {e}")
        return TelegramWebhookResponse(ok=True, action="parse_error")

    # Process the update
    result = await bot_service.handle_update(update_data)

    if result and result.get("action") == "linked":
        # User successfully linked their account
        user_id = result.get("user_id")
        chat_id = result.get("chat_id")

        if user_id and chat_id:
            # Update user's notification settings with chat_id
            try:
                # Get or create notification settings
                settings_result = await db.execute(
                    select(NotificationSettings).where(
                        NotificationSettings.user_id == user_id
                    )
                )
                notification_settings = settings_result.scalar_one_or_none()

                if notification_settings:
                    notification_settings.telegram_chat_id = chat_id
                    notification_settings.telegram_enabled = True
                else:
                    # Create new notification settings
                    notification_settings = NotificationSettings(
                        user_id=user_id,
                        telegram_chat_id=chat_id,
                        telegram_enabled=True,
                    )
                    db.add(notification_settings)

                await db.commit()
                logger.info(f"Linked Telegram chat {chat_id} to user {user_id}")

            except Exception as e:
                logger.error(f"Failed to save Telegram chat_id: {e}")
                await db.rollback()

    return TelegramWebhookResponse(
        ok=True,
        action=result.get("action") if result else None,
    )


@router.post("/disconnect")
async def disconnect_telegram(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Disconnect Telegram from user's account.

    Removes telegram_chat_id and disables Telegram notifications.
    """
    # Get notification settings
    settings_result = await db.execute(
        select(NotificationSettings).where(
            NotificationSettings.user_id == current_user.id
        )
    )
    notification_settings = settings_result.scalar_one_or_none()

    if not notification_settings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification settings not found",
        )

    # Clear Telegram settings
    notification_settings.telegram_chat_id = None
    notification_settings.telegram_enabled = False

    await db.commit()

    logger.info(f"Disconnected Telegram for user {current_user.id}")

    return {"message": "Telegram disconnected successfully"}


@router.post("/setup-webhook")
async def setup_webhook(
    current_user: User = Depends(get_current_user),
):
    """
    Set up Telegram webhook URL.

    Admin-only endpoint to configure the bot's webhook.
    The webhook URL should be configured in settings.
    """
    # TODO: Add admin check
    from app.config import get_settings
    settings = get_settings()

    if not settings.telegram_webhook_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TELEGRAM_WEBHOOK_URL not configured",
        )

    bot_service = get_telegram_bot_service()

    if not bot_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot is not configured",
        )

    success = await bot_service.set_webhook(settings.telegram_webhook_url)

    if success:
        return {"message": "Webhook configured successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set webhook",
        )
