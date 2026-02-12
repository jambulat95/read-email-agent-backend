"""
Pydantic schemas for settings API.
"""
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, EmailStr


# Notification Settings Schemas

class NotificationSettingsResponse(BaseModel):
    """Schema for notification settings response."""

    email_enabled: bool = Field(..., description="Email notifications enabled")
    telegram_enabled: bool = Field(..., description="Telegram notifications enabled")
    telegram_chat_id: Optional[str] = Field(None, description="Connected Telegram chat ID")
    telegram_connected: bool = Field(False, description="Whether Telegram is connected")
    sms_enabled: bool = Field(..., description="SMS notifications enabled")
    phone_number: Optional[str] = Field(None, description="Phone number for SMS")
    notify_on_critical: bool = Field(..., description="Notify on critical reviews")
    notify_on_important: bool = Field(..., description="Notify on important reviews")
    notify_on_normal: bool = Field(..., description="Notify on normal reviews")

    model_config = {"from_attributes": True}


class NotificationSettingsUpdate(BaseModel):
    """Schema for updating notification settings."""

    email_enabled: Optional[bool] = Field(None, description="Enable/disable email notifications")
    telegram_enabled: Optional[bool] = Field(None, description="Enable/disable Telegram notifications")
    sms_enabled: Optional[bool] = Field(None, description="Enable/disable SMS notifications")
    phone_number: Optional[str] = Field(
        None, description="Phone number for SMS", max_length=20
    )
    notify_on_critical: Optional[bool] = Field(None, description="Notify on critical reviews")
    notify_on_important: Optional[bool] = Field(None, description="Notify on important reviews")
    notify_on_normal: Optional[bool] = Field(None, description="Notify on normal reviews")


# Company Settings Schemas

class CompanySettingsResponse(BaseModel):
    """Schema for company settings response."""

    company_name: Optional[str] = Field(None, description="Company name")
    response_tone: str = Field(..., description="Default response tone (formal/friendly/professional)")
    custom_templates: Optional[Dict[str, Any]] = Field(
        None, description="Custom response templates"
    )

    model_config = {"from_attributes": True}


class CompanySettingsUpdate(BaseModel):
    """Schema for updating company settings."""

    company_name: Optional[str] = Field(
        None, description="Company name", max_length=255
    )
    response_tone: Optional[Literal["formal", "friendly", "professional"]] = Field(
        None, description="Default response tone"
    )
    custom_templates: Optional[Dict[str, Any]] = Field(
        None, description="Custom response templates"
    )


# Profile Schemas

class ProfileResponse(BaseModel):
    """Schema for user profile response."""

    email: str = Field(..., description="User email")
    full_name: str = Field(..., description="User full name")
    plan: str = Field(..., description="Current subscription plan")
    is_verified: bool = Field(..., description="Email verification status")

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    """Schema for updating user profile."""

    full_name: Optional[str] = Field(
        None, description="Full name", min_length=1, max_length=255
    )
    email: Optional[EmailStr] = Field(None, description="New email address")
