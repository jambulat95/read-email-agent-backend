"""
Celery tasks for AI analysis of reviews.

Contains:
- analyze_review: Task to analyze a single review using AI
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
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


@celery_app.task(
    bind=True,
    name="app.tasks.ai_tasks.analyze_review",
    max_retries=3,
    default_retry_delay=30,
    retry_backoff=True,
    retry_backoff_max=300,  # Max 5 minutes between retries
    retry_jitter=True,
)
def analyze_review(self, review_id: str) -> dict:
    """
    Analyze a review using AI.

    Steps:
    1. Get Review from database
    2. Get email text via Gmail API
    3. Determine user plan for analysis depth
    4. Run AI analysis
    5. Save results to Review
    6. If negative/critical - trigger notification (future task)

    Args:
        review_id: UUID of the Review to analyze

    Returns:
        Dict with analysis results
    """
    logger.info(f"Starting AI analysis for review {review_id}")

    db = get_sync_session()

    try:
        # 1. Get Review from database
        review_uuid = UUID(review_id)
        result = db.execute(
            select(Review)
            .where(Review.id == review_uuid)
        )
        review = result.scalar_one_or_none()

        if not review:
            logger.error(f"Review {review_id} not found")
            return {
                "success": False,
                "error": "Review not found",
                "review_id": review_id,
            }

        if review.is_processed:
            logger.info(f"Review {review_id} already processed, skipping")
            return {
                "success": True,
                "message": "Already processed",
                "review_id": review_id,
            }

        # 2. Get EmailAccount and User to determine plan
        account_result = db.execute(
            select(EmailAccount)
            .where(EmailAccount.id == review.email_account_id)
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
            select(User)
            .where(User.id == email_account.user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            logger.error(f"User for email account not found")
            return {
                "success": False,
                "error": "User not found",
                "review_id": review_id,
            }

        # 3. Get email text via Gmail API
        try:
            gmail_client = GmailClient(email_account)
            message_details = gmail_client.get_message_details(review.message_id)
            email_text = message_details.body_text or ""

            if not email_text:
                logger.warning(f"No body text for review {review_id}")
                email_text = review.subject  # Fallback to subject

        except GmailAuthError as e:
            logger.error(f"Gmail auth error for review {review_id}: {e}")
            # Mark account as inactive
            email_account.is_active = False
            db.commit()
            return {
                "success": False,
                "error": f"Gmail auth error: {e}",
                "review_id": review_id,
            }
        except GmailClientError as e:
            logger.error(f"Gmail client error for review {review_id}: {e}")
            # Retry for temporary errors
            raise self.retry(exc=e, countdown=60)

        # 4. Run AI analysis
        try:
            from app.services.ai_analysis import get_review_analyzer

            analyzer = get_review_analyzer()

            # Determine analysis depth based on plan
            # FREE: basic analysis (sentiment + priority only)
            # STARTER+: full analysis with problems and suggestions
            use_full_analysis = user.plan != PlanType.FREE

            if use_full_analysis:
                analysis = analyzer.analyze(email_text, review.subject)
            else:
                analysis = analyzer.analyze_basic(email_text, review.subject)

            logger.info(
                f"Analysis complete for review {review_id}: "
                f"sentiment={analysis.sentiment}, priority={analysis.priority}"
            )

        except ValueError as e:
            # Missing API key or configuration
            logger.error(f"AI configuration error: {e}")
            return {
                "success": False,
                "error": f"AI configuration error: {e}",
                "review_id": review_id,
            }
        except Exception as e:
            logger.error(f"AI analysis error for review {review_id}: {e}")
            # Retry for API errors
            try:
                raise self.retry(exc=e, countdown=60)
            except MaxRetriesExceededError:
                # Mark as failed after max retries
                review.is_processed = True
                review.processed_at = datetime.now(timezone.utc)
                # Store error in summary field
                review.summary = f"[Analysis failed: {str(e)[:200]}]"
                db.commit()
                logger.error(f"Max retries exceeded for review {review_id}")
                return {
                    "success": False,
                    "error": f"Max retries exceeded: {e}",
                    "review_id": review_id,
                    "analysis_failed": True,
                }

        # 5. Save results to Review
        review.sentiment = analysis.sentiment
        review.priority = analysis.priority
        review.summary = analysis.summary
        review.problems = analysis.problems
        review.suggestions = analysis.suggestions
        review.is_processed = True
        review.processed_at = datetime.now(timezone.utc)

        db.commit()

        logger.info(f"Saved analysis results for review {review_id}")

        # 6. If negative/critical - trigger notification
        if analysis.sentiment == "negative" or analysis.priority == "critical":
            logger.info(
                f"Review {review_id} is negative/critical, triggering notification"
            )
            from app.tasks.notification_tasks import send_notification
            send_notification.delay(review_id)

        # 7. Generate response drafts for STARTER+ plans
        if user.plan != PlanType.FREE:
            logger.info(
                f"User plan is {user.plan}, triggering response draft generation"
            )
            from app.tasks.response_tasks import generate_response_drafts
            generate_response_drafts.delay(review_id)

        return {
            "success": True,
            "review_id": review_id,
            "sentiment": analysis.sentiment,
            "priority": analysis.priority,
            "requires_response": analysis.requires_response,
            "problems_count": len(analysis.problems),
            "suggestions_count": len(analysis.suggestions),
        }

    except MaxRetriesExceededError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error analyzing review {review_id}: {e}")
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
