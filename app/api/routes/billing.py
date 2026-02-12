"""
Billing API routes for Stripe subscription management.

Endpoints:
- POST /billing/checkout - Create checkout session
- GET  /billing/portal - Get customer portal URL
- POST /billing/cancel - Cancel subscription
- GET  /billing/subscription - Get current subscription
- GET  /billing/invoices - List invoices
- GET  /billing/usage - Get current usage
- POST /billing/webhook - Stripe webhook (no auth)
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.database import get_async_session
from app.models.enums import PlanType
from app.models.user import User
from app.schemas.billing import (
    CheckoutRequest,
    CheckoutResponse,
    InvoiceListResponse,
    InvoiceResponse,
    PortalResponse,
    SubscriptionResponse,
    UsageResponse,
)
from app.services.billing import BillingService
from app.services.plan_limits import PLAN_LIMITS
from app.services.usage_tracker import UsageTracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    data: CheckoutRequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Create a Stripe Checkout Session for plan upgrade."""
    try:
        plan = PlanType(data.plan)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid plan: {data.plan}. Must be starter, professional, or enterprise.",
        )

    if plan == PlanType.FREE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot checkout for free plan",
        )

    if data.billing_period not in ("monthly", "yearly"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="billing_period must be 'monthly' or 'yearly'",
        )

    billing_service = BillingService(db)
    try:
        url = await billing_service.create_checkout_session(
            user=user,
            plan=plan,
            billing_period=data.billing_period,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return CheckoutResponse(url=url)


@router.get("/portal", response_model=PortalResponse)
async def get_portal_url(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get Stripe Customer Portal URL for managing subscription."""
    billing_service = BillingService(db)
    url = await billing_service.create_portal_session(user)
    return PortalResponse(url=url)


@router.post("/cancel", status_code=status.HTTP_200_OK)
async def cancel_subscription(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Cancel the current subscription at end of billing period."""
    billing_service = BillingService(db)
    try:
        await billing_service.cancel_subscription(user)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    return {"message": "Subscription will be canceled at end of billing period"}


@router.get("/subscription")
async def get_subscription(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get current subscription details."""
    billing_service = BillingService(db)
    subscription = await billing_service.get_subscription(user.id)

    if not subscription:
        return {
            "plan": user.plan,
            "status": "active" if user.plan == PlanType.FREE else "none",
            "cancel_at_period_end": False,
        }

    return SubscriptionResponse.model_validate(subscription)


@router.get("/invoices", response_model=InvoiceListResponse)
async def get_invoices(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """List all invoices for the current user."""
    billing_service = BillingService(db)
    invoices = await billing_service.get_invoices(user.id)
    return InvoiceListResponse(
        items=[InvoiceResponse.model_validate(inv) for inv in invoices]
    )


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get current usage statistics against plan limits."""
    tracker = UsageTracker(db)
    plan = PlanType(user.plan)
    limits = PLAN_LIMITS[plan]

    emails_used = await tracker.get_monthly_usage(user.id)
    accounts_used = await tracker.get_email_accounts_count(user.id)

    # Get period from subscription if available
    billing_service = BillingService(db)
    subscription = await billing_service.get_subscription(user.id)

    return UsageResponse(
        emails_used=emails_used,
        emails_limit=limits["emails_per_month"],
        email_accounts_used=accounts_used,
        email_accounts_limit=limits["email_accounts"],
        period_start=subscription.current_period_start if subscription else None,
        period_end=subscription.current_period_end if subscription else None,
    )


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Stripe webhook endpoint.

    No authentication required - verified via Stripe signature.
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    billing_service = BillingService(db)
    try:
        await billing_service.handle_webhook(payload, signature)
    except ValueError as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return {"status": "ok"}
