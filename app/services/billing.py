"""
Billing service for Stripe integration.

Handles:
- Customer creation
- Checkout session creation
- Customer portal sessions
- Subscription management
- Webhook event processing
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import PlanType, SubscriptionStatus
from app.models.invoice import Invoice
from app.models.subscription import Subscription
from app.models.user import User

logger = logging.getLogger(__name__)
settings = get_settings()

# Configure Stripe
stripe.api_key = settings.stripe_secret_key

# Map Stripe price IDs to plan types
PRICE_TO_PLAN = {}
PLAN_TO_PRICES = {}


def _init_price_mappings():
    """Initialize price-to-plan mappings from settings."""
    global PRICE_TO_PLAN, PLAN_TO_PRICES

    mapping = {
        settings.stripe_price_starter_monthly: PlanType.STARTER,
        settings.stripe_price_starter_yearly: PlanType.STARTER,
        settings.stripe_price_pro_monthly: PlanType.PROFESSIONAL,
        settings.stripe_price_pro_yearly: PlanType.PROFESSIONAL,
        settings.stripe_price_enterprise_monthly: PlanType.ENTERPRISE,
    }
    PRICE_TO_PLAN = {k: v for k, v in mapping.items() if k}

    PLAN_TO_PRICES = {
        PlanType.STARTER: {
            "monthly": settings.stripe_price_starter_monthly,
            "yearly": settings.stripe_price_starter_yearly,
        },
        PlanType.PROFESSIONAL: {
            "monthly": settings.stripe_price_pro_monthly,
            "yearly": settings.stripe_price_pro_yearly,
        },
        PlanType.ENTERPRISE: {
            "monthly": settings.stripe_price_enterprise_monthly,
        },
    }


_init_price_mappings()

# Webhook events we handle
WEBHOOK_EVENTS = [
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
]


class BillingService:
    """Manages Stripe billing operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_customer(self, user: User) -> str:
        """Get existing Stripe customer ID or create a new one."""
        # Check if user already has a subscription with customer ID
        result = await self.db.execute(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        subscription = result.scalar_one_or_none()

        if subscription and subscription.stripe_customer_id:
            return subscription.stripe_customer_id

        # Create new Stripe customer
        customer = stripe.Customer.create(
            email=user.email,
            name=user.full_name,
            metadata={"user_id": str(user.id)},
        )

        return customer.id

    async def create_checkout_session(
        self,
        user: User,
        plan: PlanType,
        billing_period: str = "monthly",
    ) -> str:
        """
        Create a Stripe Checkout Session and return the URL.

        Args:
            user: The user requesting checkout
            plan: Target plan
            billing_period: 'monthly' or 'yearly'

        Returns:
            Checkout session URL
        """
        prices = PLAN_TO_PRICES.get(plan)
        if not prices:
            raise ValueError(f"No pricing configured for plan: {plan.value}")

        price_id = prices.get(billing_period)
        if not price_id:
            raise ValueError(f"No {billing_period} pricing for plan: {plan.value}")

        customer_id = await self.get_or_create_customer(user)

        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=f"{settings.frontend_url}/dashboard/billing?success=true",
            cancel_url=f"{settings.frontend_url}/dashboard/billing?canceled=true",
            metadata={
                "user_id": str(user.id),
                "plan": plan.value,
            },
            subscription_data={
                "metadata": {
                    "user_id": str(user.id),
                    "plan": plan.value,
                },
            },
        )

        return session.url

    async def create_portal_session(self, user: User) -> str:
        """
        Create a Stripe Customer Portal session for managing subscriptions.

        Returns:
            Portal session URL
        """
        customer_id = await self.get_or_create_customer(user)

        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{settings.frontend_url}/dashboard/billing",
        )

        return session.url

    async def cancel_subscription(self, user: User) -> None:
        """Cancel user's subscription at the end of the billing period."""
        result = await self.db.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription or not subscription.stripe_subscription_id:
            raise ValueError("No active subscription found")

        # Cancel at period end (not immediately)
        stripe.Subscription.modify(
            subscription.stripe_subscription_id,
            cancel_at_period_end=True,
        )

        subscription.cancel_at_period_end = True
        await self.db.flush()

    async def get_subscription(self, user_id: UUID) -> Optional[Subscription]:
        """Get the user's current subscription."""
        result = await self.db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_invoices(self, user_id: UUID) -> list[Invoice]:
        """Get all invoices for a user's subscription."""
        result = await self.db.execute(
            select(Invoice)
            .join(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(Invoice.created_at.desc())
        )
        return list(result.scalars().all())

    # --- Webhook handlers ---

    async def handle_webhook(self, payload: bytes, signature: str) -> None:
        """
        Process a Stripe webhook event.

        Args:
            payload: Raw request body
            signature: Stripe-Signature header
        """
        try:
            event = stripe.Webhook.construct_event(
                payload,
                signature,
                settings.stripe_webhook_secret,
            )
        except stripe.SignatureVerificationError:
            raise ValueError("Invalid webhook signature")

        event_type = event["type"]
        logger.info(f"Processing Stripe webhook: {event_type}")

        if event_type == "checkout.session.completed":
            await self._handle_checkout_completed(event["data"]["object"])
        elif event_type == "customer.subscription.updated":
            await self._handle_subscription_updated(event["data"]["object"])
        elif event_type == "customer.subscription.deleted":
            await self._handle_subscription_deleted(event["data"]["object"])
        elif event_type == "invoice.paid":
            await self._handle_invoice_paid(event["data"]["object"])
        elif event_type == "invoice.payment_failed":
            await self._handle_payment_failed(event["data"]["object"])
        else:
            logger.info(f"Unhandled webhook event: {event_type}")

    async def _handle_checkout_completed(self, session: dict) -> None:
        """Handle successful checkout: create/update subscription."""
        user_id_str = session.get("metadata", {}).get("user_id")
        plan_str = session.get("metadata", {}).get("plan")

        if not user_id_str or not plan_str:
            logger.error("Missing metadata in checkout session")
            return

        user_id = UUID(user_id_str)
        plan = PlanType(plan_str)
        customer_id = session["customer"]
        stripe_sub_id = session.get("subscription")

        # Get or create subscription record
        result = await self.db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        # Get subscription details from Stripe
        period_start = None
        period_end = None
        if stripe_sub_id:
            try:
                stripe_sub = stripe.Subscription.retrieve(stripe_sub_id)
                period_start = datetime.fromtimestamp(
                    stripe_sub["current_period_start"], tz=timezone.utc
                )
                period_end = datetime.fromtimestamp(
                    stripe_sub["current_period_end"], tz=timezone.utc
                )
            except Exception as e:
                logger.error(f"Failed to retrieve subscription details: {e}")

        if subscription:
            subscription.stripe_customer_id = customer_id
            subscription.stripe_subscription_id = stripe_sub_id
            subscription.plan = plan
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.current_period_start = period_start
            subscription.current_period_end = period_end
            subscription.cancel_at_period_end = False
        else:
            subscription = Subscription(
                user_id=user_id,
                stripe_customer_id=customer_id,
                stripe_subscription_id=stripe_sub_id,
                plan=plan,
                status=SubscriptionStatus.ACTIVE,
                current_period_start=period_start,
                current_period_end=period_end,
            )
            self.db.add(subscription)

        # Update user plan
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.plan = plan
            user.plan_expires_at = period_end

        await self.db.flush()
        logger.info(f"Checkout completed: user={user_id}, plan={plan.value}")

    async def _handle_subscription_updated(self, sub_data: dict) -> None:
        """Handle subscription changes (plan change, renewal, etc.)."""
        stripe_sub_id = sub_data["id"]
        customer_id = sub_data["customer"]

        result = await self.db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_sub_id
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            logger.warning(f"Subscription {stripe_sub_id} not found in DB")
            return

        # Update status
        stripe_status = sub_data["status"]
        status_map = {
            "active": SubscriptionStatus.ACTIVE,
            "past_due": SubscriptionStatus.PAST_DUE,
            "canceled": SubscriptionStatus.CANCELED,
            "trialing": SubscriptionStatus.TRIALING,
            "incomplete": SubscriptionStatus.INCOMPLETE,
        }
        subscription.status = status_map.get(stripe_status, SubscriptionStatus.ACTIVE)

        # Update period
        subscription.current_period_start = datetime.fromtimestamp(
            sub_data["current_period_start"], tz=timezone.utc
        )
        subscription.current_period_end = datetime.fromtimestamp(
            sub_data["current_period_end"], tz=timezone.utc
        )
        subscription.cancel_at_period_end = sub_data.get("cancel_at_period_end", False)

        # Detect plan change from price
        items = sub_data.get("items", {}).get("data", [])
        if items:
            price_id = items[0].get("price", {}).get("id")
            if price_id and price_id in PRICE_TO_PLAN:
                new_plan = PRICE_TO_PLAN[price_id]
                subscription.plan = new_plan

                # Update user plan
                result = await self.db.execute(
                    select(User).where(User.id == subscription.user_id)
                )
                user = result.scalar_one_or_none()
                if user:
                    user.plan = new_plan
                    user.plan_expires_at = subscription.current_period_end

        await self.db.flush()
        logger.info(f"Subscription updated: {stripe_sub_id}, status={stripe_status}")

    async def _handle_subscription_deleted(self, sub_data: dict) -> None:
        """Handle subscription cancellation/expiration."""
        stripe_sub_id = sub_data["id"]

        result = await self.db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_sub_id
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            return

        subscription.status = SubscriptionStatus.CANCELED

        # Downgrade user to FREE
        result = await self.db.execute(
            select(User).where(User.id == subscription.user_id)
        )
        user = result.scalar_one_or_none()
        if user:
            user.plan = PlanType.FREE
            user.plan_expires_at = None

        await self.db.flush()
        logger.info(f"Subscription deleted: {stripe_sub_id}, user downgraded to FREE")

    async def _handle_invoice_paid(self, invoice_data: dict) -> None:
        """Record a paid invoice."""
        stripe_invoice_id = invoice_data["id"]
        stripe_sub_id = invoice_data.get("subscription")

        if not stripe_sub_id:
            return

        result = await self.db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_sub_id
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            return

        # Check for duplicate
        existing = await self.db.execute(
            select(Invoice).where(Invoice.stripe_invoice_id == stripe_invoice_id)
        )
        if existing.scalar_one_or_none():
            return

        invoice = Invoice(
            subscription_id=subscription.id,
            stripe_invoice_id=stripe_invoice_id,
            amount=invoice_data.get("amount_paid", 0),
            currency=invoice_data.get("currency", "usd"),
            status="paid",
            paid_at=datetime.now(timezone.utc),
            pdf_url=invoice_data.get("invoice_pdf"),
        )
        self.db.add(invoice)
        await self.db.flush()

        logger.info(f"Invoice recorded: {stripe_invoice_id}, amount={invoice.amount}")

    async def _handle_payment_failed(self, invoice_data: dict) -> None:
        """Handle failed payment: mark subscription as past_due."""
        stripe_sub_id = invoice_data.get("subscription")

        if not stripe_sub_id:
            return

        result = await self.db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_sub_id
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            return

        subscription.status = SubscriptionStatus.PAST_DUE
        await self.db.flush()

        logger.info(
            f"Payment failed for subscription {stripe_sub_id}, "
            f"user_id={subscription.user_id}"
        )
