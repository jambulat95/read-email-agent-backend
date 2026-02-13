"""
API routes for user settings management.

Endpoints:
- GET/PATCH /api/settings/notifications - Notification preferences
- GET/PATCH /api/settings/company - Company settings
- GET/PATCH /api/settings/profile - User profile
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.database import get_async_session
from app.models.company_settings import CompanySettings
from app.models.enums import PlanType, ResponseTone
from app.models.notification_settings import NotificationSettings
from app.models.user import User
from app.schemas.settings import (
    CompanySettingsResponse,
    CompanySettingsUpdate,
    NotificationSettingsResponse,
    NotificationSettingsUpdate,
    ProfileResponse,
    ProfileUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


# ===== Notification Settings Endpoints =====

@router.get(
    "/notifications",
    response_model=NotificationSettingsResponse,
    summary="Get notification settings",
    description="Returns current notification preferences for the user.",
)
async def get_notification_settings(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> NotificationSettingsResponse:
    """
    Get user's notification settings.

    Args:
        user: Current authenticated user
        db: Database session

    Returns:
        Notification settings
    """
    # Get or create notification settings
    result = await db.execute(
        select(NotificationSettings).where(NotificationSettings.user_id == user.id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        # Create default settings
        settings = NotificationSettings(
            user_id=user.id,
            email_enabled=True,
            telegram_enabled=False,
            sms_enabled=False,
            notify_on_critical=True,
            notify_on_important=True,
            notify_on_normal=False,
        )
        db.add(settings)
        await db.flush()

    return NotificationSettingsResponse(
        email_enabled=settings.email_enabled,
        telegram_enabled=settings.telegram_enabled,
        telegram_chat_id=settings.telegram_chat_id,
        telegram_connected=bool(settings.telegram_chat_id),
        sms_enabled=settings.sms_enabled,
        phone_number=settings.phone_number,
        notify_on_critical=settings.notify_on_critical,
        notify_on_important=settings.notify_on_important,
        notify_on_normal=settings.notify_on_normal,
    )


@router.patch(
    "/notifications",
    response_model=NotificationSettingsResponse,
    summary="Update notification settings",
    description="Update notification preferences. SMS notifications require PRO plan or higher.",
)
async def update_notification_settings(
    data: NotificationSettingsUpdate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> NotificationSettingsResponse:
    """
    Update user's notification settings.

    Args:
        data: Update data
        user: Current authenticated user
        db: Database session

    Returns:
        Updated notification settings
    """
    # Check SMS plan restriction
    if data.sms_enabled is True:
        user_plan = PlanType(user.plan)
        if user_plan not in [PlanType.PROFESSIONAL, PlanType.ENTERPRISE]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="SMS notifications require PRO plan or higher.",
            )

    # Get or create settings
    result = await db.execute(
        select(NotificationSettings).where(NotificationSettings.user_id == user.id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = NotificationSettings(user_id=user.id)
        db.add(settings)

    # Update fields
    if data.email_enabled is not None:
        settings.email_enabled = data.email_enabled
    if data.telegram_enabled is not None:
        settings.telegram_enabled = data.telegram_enabled
    if data.sms_enabled is not None:
        settings.sms_enabled = data.sms_enabled
    if data.phone_number is not None:
        settings.phone_number = data.phone_number
    if data.notify_on_critical is not None:
        settings.notify_on_critical = data.notify_on_critical
    if data.notify_on_important is not None:
        settings.notify_on_important = data.notify_on_important
    if data.notify_on_normal is not None:
        settings.notify_on_normal = data.notify_on_normal

    await db.flush()

    return NotificationSettingsResponse(
        email_enabled=settings.email_enabled,
        telegram_enabled=settings.telegram_enabled,
        telegram_chat_id=settings.telegram_chat_id,
        telegram_connected=bool(settings.telegram_chat_id),
        sms_enabled=settings.sms_enabled,
        phone_number=settings.phone_number,
        notify_on_critical=settings.notify_on_critical,
        notify_on_important=settings.notify_on_important,
        notify_on_normal=settings.notify_on_normal,
    )


# ===== Company Settings Endpoints =====

@router.get(
    "/company",
    response_model=CompanySettingsResponse,
    summary="Get company settings",
    description="Returns company settings including response tone preferences.",
)
async def get_company_settings(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> CompanySettingsResponse:
    """
    Get user's company settings.

    Args:
        user: Current authenticated user
        db: Database session

    Returns:
        Company settings
    """
    result = await db.execute(
        select(CompanySettings).where(CompanySettings.user_id == user.id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        # Create default settings
        settings = CompanySettings(
            user_id=user.id,
            response_tone=ResponseTone.PROFESSIONAL,
        )
        db.add(settings)
        await db.flush()

    return CompanySettingsResponse(
        company_name=settings.company_name,
        industry=settings.industry,
        response_tone=settings.response_tone,
        custom_instructions=settings.custom_instructions,
    )


@router.patch(
    "/company",
    response_model=CompanySettingsResponse,
    summary="Update company settings",
    description="Update company settings including name and response tone.",
)
async def update_company_settings(
    data: CompanySettingsUpdate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> CompanySettingsResponse:
    """
    Update user's company settings.

    Args:
        data: Update data
        user: Current authenticated user
        db: Database session

    Returns:
        Updated company settings
    """
    result = await db.execute(
        select(CompanySettings).where(CompanySettings.user_id == user.id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        settings = CompanySettings(
            user_id=user.id,
            response_tone=ResponseTone.PROFESSIONAL,
        )
        db.add(settings)

    # Update fields
    if data.company_name is not None:
        settings.company_name = data.company_name
    if data.industry is not None:
        settings.industry = data.industry
    if data.response_tone is not None:
        settings.response_tone = ResponseTone(data.response_tone)
    if data.custom_instructions is not None:
        settings.custom_instructions = data.custom_instructions

    await db.flush()

    return CompanySettingsResponse(
        company_name=settings.company_name,
        industry=settings.industry,
        response_tone=settings.response_tone,
        custom_instructions=settings.custom_instructions,
    )


# ===== Profile Endpoints =====

@router.get(
    "/profile",
    response_model=ProfileResponse,
    summary="Get user profile",
    description="Returns user profile information.",
)
async def get_profile(
    user: User = Depends(get_current_active_user),
) -> ProfileResponse:
    """
    Get user profile.

    Args:
        user: Current authenticated user

    Returns:
        User profile
    """
    return ProfileResponse(
        email=user.email,
        full_name=user.full_name,
        plan=user.plan,
        is_verified=user.is_verified,
    )


@router.patch(
    "/profile",
    response_model=ProfileResponse,
    summary="Update user profile",
    description="Update user profile information such as name and email.",
)
async def update_profile(
    data: ProfileUpdate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> ProfileResponse:
    """
    Update user profile.

    Args:
        data: Update data
        user: Current authenticated user
        db: Database session

    Returns:
        Updated user profile
    """
    # Check if email is being changed and if it's already in use
    if data.email and data.email != user.email:
        result = await db.execute(
            select(User).where(User.email == data.email)
        )
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use by another account.",
            )
        user.email = data.email
        user.is_verified = False  # Require re-verification

    if data.full_name is not None:
        user.full_name = data.full_name

    await db.flush()

    return ProfileResponse(
        email=user.email,
        full_name=user.full_name,
        plan=user.plan,
        is_verified=user.is_verified,
    )
