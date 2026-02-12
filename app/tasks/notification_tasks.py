"""
Celery tasks for sending notifications.

Contains:
- send_notification: Send notification about a review
- send_weekly_reports: Weekly report generation and sending (scheduled)
"""
import asyncio
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models.email_account import EmailAccount
from app.models.enums import PlanType
from app.models.review import Review
from app.models.user import User
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()

# Plans with access to weekly reports
REPORT_PLANS = {PlanType.PROFESSIONAL.value, PlanType.ENTERPRISE.value}


def get_sync_session() -> Session:
    """Create a synchronous database session for Celery tasks."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    sync_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    sync_engine = create_engine(sync_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)
    return SessionLocal()


def get_async_session_for_celery():
    """Create an async session for use within Celery tasks (via run_async)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    return session_maker, engine


def run_async(coro):
    """Run async coroutine in sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    bind=True,
    name="app.tasks.notification_tasks.send_notification",
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    retry_backoff_max=300,
)
def send_notification(self, review_id: str) -> dict:
    """
    Send notification about a review to the user.

    Args:
        review_id: UUID of the Review to notify about

    Returns:
        Dict with notification results
    """
    logger.info(f"Starting notification task for review {review_id}")

    db = get_sync_session()

    try:
        review_uuid = UUID(review_id)
        result = db.execute(
            select(Review)
            .where(Review.id == review_uuid)
            .options(joinedload(Review.email_account))
        )
        review = result.scalar_one_or_none()

        if not review:
            logger.error(f"Review {review_id} not found")
            return {
                "success": False,
                "error": "Review not found",
                "review_id": review_id,
            }

        user_result = db.execute(
            select(User)
            .where(User.id == review.email_account.user_id)
            .options(joinedload(User.notification_settings))
        )
        user = user_result.scalar_one_or_none()

        if not user:
            logger.error(f"User for review {review_id} not found")
            return {
                "success": False,
                "error": "User not found",
                "review_id": review_id,
            }

        from app.services.notification_service import get_notification_service

        service = get_notification_service()
        summary = run_async(service.send_review_notification(review, user))

        logger.info(
            f"Notification task completed for review {review_id}: "
            f"{summary.successful}/{summary.total_channels} successful"
        )

        return {
            "success": summary.any_successful,
            "review_id": review_id,
            "total_channels": summary.total_channels,
            "successful": summary.successful,
            "failed": summary.failed,
            "results": [
                {
                    "channel": r.channel,
                    "success": r.success,
                    "error": r.error,
                    "message_id": r.message_id,
                }
                for r in summary.results
            ],
        }

    except Exception as e:
        logger.error(f"Error in notification task for review {review_id}: {e}")
        try:
            raise self.retry(exc=e, countdown=60)
        except self.MaxRetriesExceededError:
            return {
                "success": False,
                "error": f"Max retries exceeded: {e}",
                "review_id": review_id,
            }

    finally:
        db.close()


@celery_app.task(
    name="app.tasks.notification_tasks.send_weekly_reports",
)
def send_weekly_reports() -> dict:
    """
    Generate and send weekly reports to Pro/Enterprise users.

    Scheduled to run every Monday at 9:00 AM.

    Returns:
        Dict with summary of generated/sent reports
    """
    logger.info("Starting weekly reports task")

    db = get_sync_session()

    try:
        # Get Pro/Enterprise users with active accounts
        result = db.execute(
            select(User)
            .where(
                User.is_active == True,
                User.plan.in_(list(REPORT_PLANS)),
            )
            .options(joinedload(User.notification_settings))
        )
        users = result.unique().scalars().all()

        generated_count = 0
        sent_count = 0
        failed_count = 0

        for user in users:
            try:
                # Generate and send report via async service
                async def _process_user(user_obj):
                    session_maker, engine = get_async_session_for_celery()
                    async with session_maker() as async_db:
                        try:
                            from app.services.weekly_report import WeeklyReportService
                            service = WeeklyReportService(async_db)

                            # Generate report
                            report = await service.generate_report(user_obj.id)
                            nonlocal generated_count
                            generated_count += 1

                            # Generate PDF
                            try:
                                await service.generate_pdf(report)
                            except Exception as pdf_err:
                                logger.warning(f"PDF generation failed for user {user_obj.id}: {pdf_err}")

                            # Send email if notifications enabled
                            if user_obj.notification_settings and user_obj.notification_settings.email_enabled:
                                sent = await service.send_report(user_obj, report)
                                if sent:
                                    nonlocal sent_count
                                    sent_count += 1
                        finally:
                            await async_db.close()
                    await engine.dispose()

                run_async(_process_user(user))

            except Exception as e:
                logger.error(f"Error generating report for user {user.id}: {e}")
                failed_count += 1

        logger.info(
            f"Weekly reports task completed: {generated_count} generated, "
            f"{sent_count} sent, {failed_count} failed"
        )

        return {
            "success": True,
            "total_users": len(users),
            "generated": generated_count,
            "sent": sent_count,
            "failed": failed_count,
        }

    except Exception as e:
        logger.error(f"Error in weekly reports task: {e}")
        return {
            "success": False,
            "error": str(e),
        }

    finally:
        db.close()
