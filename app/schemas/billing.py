"""
Pydantic schemas for billing and subscriptions.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CheckoutRequest(BaseModel):
    """Request to create a Stripe checkout session."""
    plan: str = Field(..., description="Plan: starter, professional, enterprise")
    billing_period: str = Field("monthly", description="Billing period: monthly or yearly")


class CheckoutResponse(BaseModel):
    """Response with checkout session URL."""
    url: str


class PortalResponse(BaseModel):
    """Response with customer portal URL."""
    url: str


class SubscriptionResponse(BaseModel):
    """Current subscription details."""
    id: UUID
    plan: str
    status: str
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class InvoiceResponse(BaseModel):
    """Invoice details."""
    id: UUID
    stripe_invoice_id: str
    amount: int
    currency: str
    status: str
    paid_at: Optional[datetime] = None
    pdf_url: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvoiceListResponse(BaseModel):
    """List of invoices."""
    items: List[InvoiceResponse]


class UsageResponse(BaseModel):
    """Current usage statistics."""
    emails_used: int
    emails_limit: int
    email_accounts_used: int
    email_accounts_limit: int
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
