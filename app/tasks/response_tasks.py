"""
Celery tasks for response generation.

Contains:
- generate_response_drafts: Task to generate draft responses for a review
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.company_settings import CompanySettings
from app.models.draft_response import DraftResponse
from app.models.email_account import EmailAccount
from app.models.enums import PlanType
from app.models.review import Review
from app.models.user import User
from app.services.gmail_client import (
    GmailAuthError,
    GmailClient,
    GmailClientError,
)
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()


# Plan-based variant limits
PLAN_VARIANT_LIMITS = {
    PlanType.FREE: 0,  # No drafts for FREE
    PlanType.STARTER: 1,  # 1 variant
    PlanType.PROFESSIONAL: 3,  # 3 variants
    PlanType.ENTERPRISE: 3,  # 3 variants
}


def get_sync_session() -> Session:
    """
    Create a synchronous database session for Celery tasks.

    Celery tasks run synchronously, so we need a sync session.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Convert async URL to sync URL
    sync_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql://"
    )

    sync_engine = create_engine(sync_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)
    return SessionLocal()


def _run_async(coro):
    """Run an async coroutine in a sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    bind=True,
    name="app.tasks.response_tasks.generate_response_drafts",
    max_retries=3,
    default_retry_delay=30,
    retry_backoff=True,
    retry_backoff_max=300,  # Max 5 minutes between retries
    retry_jitter=True,
)
def generate_response_drafts(self, review_id: str) -> dict:
    """
    Generate draft responses for a review.

    Steps:
    1. Get Review from database
    2. Check user plan and determine number of variants
    3. Get review text via Gmail API (if needed)
    4. Get company settings
    5. Generate response drafts using AI
    6. Save drafts to database

    Args:
        review_id: UUID of the Review to generate responses for

    Returns:
        Dict with generation results
    """
    logger.info(f"Starting response generation for review {review_id}")

    db = get_sync_session()

    try:
        # 1. Get Review from database
        review_uuid = UUID(review_id)
        result = db.execute(
            select(Review).where(Review.id == review_uuid)
        )
        review = result.scalar_one_or_none()

        if not review:
            logger.error(f"Review {review_id} not found")
            return {
                "success": False,
                "error": "Review not found",
                "review_id": review_id,
            }

        if not review.is_processed:
            logger.warning(f"Review {review_id} not yet processed, skipping response generation")
            return {
                "success": False,
                "error": "Review not yet processed",
                "review_id": review_id,
            }

        # 2. Get EmailAccount and User
        account_result = db.execute(
            select(EmailAccount).where(EmailAccount.id == review.email_account_id)
        )
        email_account = account_result.scalar_one_or_none()

        if not email_account:
            logger.error(f"EmailAccount for review {review_id} not found")
            return {
                "success": False,
                "error": "Email account not found",
                "review_id": review_id,
            }

        user_result = db.execute(
            select(User).where(User.id == email_account.user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            logger.error(f"User for email account not found")
            return {
                "success": False,
                "error": "User not found",
                "review_id": review_id,
            }

        # 3. Check plan and determine number of variants
        user_plan = PlanType(user.plan)
        num_variants = PLAN_VARIANT_LIMITS.get(user_plan, 0)

        if num_variants == 0:
            logger.info(f"User plan {user_plan} does not support draft generation")
            return {
                "success": False,
                "error": "Draft generation not available for this plan",
                "review_id": review_id,
                "plan": user_plan.value,
            }

        # 4. Get company settings
        settings_result = db.execute(
            select(CompanySettings).where(CompanySettings.user_id == user.id)
        )
        company_settings = settings_result.scalar_one_or_none()

        if not company_settings:
            # Create default settings if not exist
            logger.info(f"Creating default company settings for user {user.id}")
            company_settings = CompanySettings(
                user_id=user.id,
                company_name=None,
                response_tone="professional",
            )
            db.add(company_settings)
            db.commit()
            db.refresh(company_settings)

        # 5. Get review text
        review_text = review.summary or ""

        # Try to get full text from Gmail if available
        try:
            gmail_client = GmailClient(email_account)
            message_details = gmail_client.get_message_details(review.message_id)
            review_text = message_details.body_text or review_text
        except (GmailAuthError, GmailClientError) as e:
            logger.warning(f"Could not get review text from Gmail: {e}")
            # Use summary as fallback

        if not review_text:
            review_text = review.subject  # Last resort fallback

        # 6. Delete existing drafts for this review
        existing_drafts = db.execute(
            select(DraftResponse).where(DraftResponse.review_id == review.id)
        )
        for draft in existing_drafts.scalars().all():
            db.delete(draft)
        db.commit()

        # 7. Generate response drafts using AI
        try:
            from app.services.response_generator import get_response_generator

            generator = get_response_generator()
            drafts = _run_async(
                generator.generate_responses(
                    review=review,
                    review_text=review_text,
                    settings=company_settings,
                    num_variants=num_variants,
                )
            )

            logger.info(f"Generated {len(drafts)} drafts for review {review_id}")

        except ValueError as e:
            logger.error(f"Response generator configuration error: {e}")
            return {
                "success": False,
                "error": f"Configuration error: {e}",
                "review_id": review_id,
            }
        except Exception as e:
            logger.error(f"Error generating responses: {e}")
            try:
                raise self.retry(exc=e, countdown=60)
            except MaxRetriesExceededError:
                return {
                    "success": False,
                    "error": f"Max retries exceeded: {e}",
                    "review_id": review_id,
                }

        # 8. Save drafts to database
        saved_count = 0
        for draft in drafts:
            draft_response = DraftResponse(
                review_id=review.id,
                content=draft.content,
                tone=draft.tone,
                variant_number=draft.variant_number,
            )
            db.add(draft_response)
            saved_count += 1

        db.commit()

        logger.info(f"Saved {saved_count} draft responses for review {review_id}")

        return {
            "success": True,
            "review_id": review_id,
            "drafts_generated": saved_count,
            "tone": company_settings.response_tone,
        }

    except MaxRetriesExceededError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error generating responses for review {review_id}: {e}")
        try:
            raise self.retry(exc=e, countdown=60)
        except MaxRetriesExceededError:
            return {
                "success": False,
                "error": f"Max retries exceeded: {e}",
                "review_id": review_id,
            }

    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="app.tasks.response_tasks.regenerate_response_drafts",
    max_retries=3,
    default_retry_delay=30,
)
def regenerate_response_drafts(self, review_id: str, override_tone: Optional[str] = None) -> dict:
    """
    Regenerate draft responses for a review.

    Similar to generate_response_drafts but allows tone override.

    Args:
        review_id: UUID of the Review
        override_tone: Optional tone to use instead of company settings

    Returns:
        Dict with regeneration results
    """
    logger.info(f"Regenerating response drafts for review {review_id}")

    db = get_sync_session()

    try:
        # Get Review
        review_uuid = UUID(review_id)
        result = db.execute(
            select(Review).where(Review.id == review_uuid)
        )
        review = result.scalar_one_or_none()

        if not review:
            return {
                "success": False,
                "error": "Review not found",
                "review_id": review_id,
            }

        # Get EmailAccount and User
        account_result = db.execute(
            select(EmailAccount).where(EmailAccount.id == review.email_account_id)
        )
        email_account = account_result.scalar_one_or_none()

        if not email_account:
            return {
                "success": False,
                "error": "Email account not found",
                "review_id": review_id,
            }

        user_result = db.execute(
            select(User).where(User.id == email_account.user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            return {
                "success": False,
                "error": "User not found",
                "review_id": review_id,
            }

        # Check plan
        user_plan = PlanType(user.plan)
        num_variants = PLAN_VARIANT_LIMITS.get(user_plan, 0)

        if num_variants == 0:
            return {
                "success": False,
                "error": "Draft generation not available for this plan",
                "review_id": review_id,
            }

        # Get company settings
        settings_result = db.execute(
            select(CompanySettings).where(CompanySettings.user_id == user.id)
        )
        company_settings = settings_result.scalar_one_or_none()

        if not company_settings:
            company_settings = CompanySettings(
                user_id=user.id,
                company_name=None,
                response_tone="professional",
            )
            db.add(company_settings)
            db.commit()
            db.refresh(company_settings)

        # Override tone if specified
        if override_tone:
            company_settings.response_tone = override_tone

        # Get review text
        review_text = review.summary or review.subject

        try:
            gmail_client = GmailClient(email_account)
            message_details = gmail_client.get_message_details(review.message_id)
            review_text = message_details.body_text or review_text
        except Exception as e:
            logger.warning(f"Could not get review text: {e}")

        # Delete existing drafts
        existing_drafts = db.execute(
            select(DraftResponse).where(DraftResponse.review_id == review.id)
        )
        for draft in existing_drafts.scalars().all():
            db.delete(draft)
        db.commit()

        # Generate new drafts
        from app.services.response_generator import get_response_generator

        generator = get_response_generator()
        drafts = _run_async(
            generator.generate_responses(
                review=review,
                review_text=review_text,
                settings=company_settings,
                num_variants=num_variants,
            )
        )

        # Save drafts
        for draft in drafts:
            draft_response = DraftResponse(
                review_id=review.id,
                content=draft.content,
                tone=draft.tone,
                variant_number=draft.variant_number,
            )
            db.add(draft_response)

        db.commit()

        return {
            "success": True,
            "review_id": review_id,
            "drafts_regenerated": len(drafts),
            "tone": override_tone or company_settings.response_tone,
        }

    except Exception as e:
        logger.error(f"Error regenerating responses: {e}")
        try:
            raise self.retry(exc=e, countdown=60)
        except MaxRetriesExceededError:
            return {
                "success": False,
                "error": f"Max retries exceeded: {e}",
                "review_id": review_id,
            }

    finally:
        db.close()
