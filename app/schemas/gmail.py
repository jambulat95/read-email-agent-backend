"""
Gmail OAuth and email account schemas.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EmailAccountResponse(BaseModel):
    """Response schema for email account information."""

    id: UUID
    email: str
    provider: str
    is_active: bool
    check_interval_minutes: int
    last_checked_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EmailAccountUpdate(BaseModel):
    """Schema for updating email account settings."""

    check_interval_minutes: Optional[int] = Field(
        None,
        ge=5,
        le=1440,
        description="Check interval in minutes (5-1440)",
    )


class OAuthConnectResponse(BaseModel):
    """Response for OAuth connect endpoint."""

    authorization_url: str
    message: str = "Redirect user to authorization_url to connect Gmail"


class OAuthCallbackResponse(BaseModel):
    """Response for OAuth callback endpoint."""

    success: bool
    message: str
    email_account: Optional[EmailAccountResponse] = None
    redirect_url: str


class EmailAccountListResponse(BaseModel):
    """Response for listing email accounts."""

    accounts: list[EmailAccountResponse]
    total: int
