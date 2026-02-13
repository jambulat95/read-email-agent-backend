"""
Celery tasks for email checking and processing.

Contains:
- schedule_email_checks: Periodic task to trigger email checks for due accounts
- check_emails_for_account: Task to check emails for a single account
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import engine
from app.models.email_account import EmailAccount
from app.models.review import Review
from app.services.gmail_client import (
    GmailAuthError,
    GmailClient,
    GmailClientError,
    GmailRateLimitError,
    GmailTemporaryError,
)
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()


def get_sync_session() -> Session:
    """
    Create a synchronous database session for Celery tasks.

    Celery tasks run synchronously, so we need a sync session.
    We create a sync engine from the async URL.
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
    name="app.tasks.email_tasks.schedule_email_checks",
    max_retries=3,
    default_retry_delay=60,
)
def schedule_email_checks(self) -> dict:
    """
    Periodic task to check which accounts need email checking.

    Finds all active accounts where:
    - last_checked_at is NULL (never checked), OR
    - last_checked_at + check_interval_minutes <= now

    For each due account, dispatches check_emails_for_account task.

    Returns:
        Dict with task results
    """
    logger.info("Starting scheduled email checks")

    db = get_sync_session()
    accounts_checked = 0
    errors = []

    try:
        # Get current time
        now = datetime.now(timezone.utc)

        # Find accounts that need checking
        result = db.execute(
            select(EmailAccount).where(EmailAccount.is_active == True)
        )
        accounts = result.scalars().all()

        due_accounts = []
        for account in accounts:
            if account.last_checked_at is None:
                # Never checked - check now
                due_accounts.append(account)
            else:
                # Calculate next check time
                from datetime import timedelta

                next_check = account.last_checked_at + timedelta(
                    minutes=account.check_interval_minutes
                )
                if next_check <= now:
                    due_accounts.append(account)

        logger.info(f"Found {len(due_accounts)} accounts due for checking")

        # Dispatch tasks for each due account
        for account in due_accounts:
            try:
                check_emails_for_account.delay(str(account.id))
                accounts_checked += 1
                logger.info(f"Dispatched check task for account {account.email}")
            except Exception as e:
                error_msg = f"Failed to dispatch task for {account.email}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

    except Exception as e:
        logger.error(f"Error in schedule_email_checks: {e}")
        errors.append(str(e))
        raise self.retry(exc=e)
    finally:
        db.close()

    return {
        "accounts_dispatched": accounts_checked,
        "errors": errors,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@celery_app.task(
    bind=True,
    name="app.tasks.email_tasks.check_emails_for_account",
    max_retries=5,
    default_retry_delay=30,
    autoretry_for=(GmailTemporaryError, GmailRateLimitError),
    retry_backoff=True,
    retry_backoff_max=600,  # Max 10 minutes between retries
    retry_jitter=True,
)
def check_emails_for_account(self, email_account_id: str) -> dict:
    """
    Check for new emails for a specific account.

    Fetches emails from Gmail API, checks for duplicates,
    and saves new emails as Review records.

    Args:
        email_account_id: UUID of the EmailAccount to check

    Returns:
        Dict with check results

    Raises:
        GmailAuthError: On OAuth errors (account will be deactivated)
        GmailTemporaryError: On temporary errors (will retry)
    """
    logger.info(f"Checking emails for account {email_account_id}")

    db = get_sync_session()
    new_emails = 0
    total_fetched = 0
    errors = []

    try:
        # Get the email account
        account_uuid = UUID(email_account_id)
        result = db.execute(
            select(EmailAccount).where(EmailAccount.id == account_uuid)
        )
        account = result.scalar_one_or_none()

        if not account:
            logger.error(f"EmailAccount {email_account_id} not found")
            return {
                "success": False,
                "error": "Account not found",
                "account_id": email_account_id,
            }

        if not account.is_active:
            logger.warning(f"Account {account.email} is not active, skipping")
            return {
                "success": False,
                "error": "Account is not active",
                "account_id": email_account_id,
            }

        # Create Gmail client
        gmail_client = GmailClient(account)

        # Fetch messages since last check
        after_date = account.last_checked_at
        logger.info(
            f"Fetching emails for {account.email} after {after_date}"
        )

        try:
            logger.info(f"Calling gmail_client.get_messages for {account.email}")
            messages = gmail_client.get_messages(
                after=after_date,
                max_results=50,
            )
            total_fetched = len(messages)
            logger.info(f"Fetched {total_fetched} messages for {account.email}")

        except GmailAuthError as e:
            # OAuth error - deactivate account
            logger.error(f"OAuth error for {account.email}: {e}", exc_info=True)
            account.is_active = False
            db.commit()

            return {
                "success": False,
                "error": f"OAuth error, account deactivated: {e}",
                "account_id": email_account_id,
                "email": account.email,
            }

        except GmailRateLimitError as e:
            # Rate limit - retry later
            logger.warning(f"Rate limit for {account.email}: {e}")
            raise  # Will be retried by Celery

        except GmailTemporaryError as e:
            # Temporary error - retry
            logger.warning(f"Temporary error for {account.email}: {e}")
            raise  # Will be retried by Celery

        except Exception as e:
            # Catch any other exception from get_messages
            logger.error(f"Unexpected error fetching messages for {account.email}: {e}", exc_info=True)
            raise

        # Process each message
        for message in messages:
            try:
                # Check for duplicate by message_id
                existing = db.execute(
                    select(Review).where(
                        Review.email_account_id == account.id,
                        Review.message_id == message.message_id,
                    )
                ).scalar_one_or_none()

                if existing:
                    logger.debug(
                        f"Message {message.message_id} already exists, skipping"
                    )
                    continue

                # Create new Review record
                review = Review(
                    email_account_id=account.id,
                    message_id=message.message_id,
                    sender_email=message.sender_email,
                    sender_name=message.sender_name,
                    subject=message.subject,
                    received_at=message.received_at,
                    is_processed=False,
                )
                db.add(review)
                db.flush()  # Flush to get the review.id
                new_emails += 1

                logger.info(
                    f"Created review for message {message.message_id}: "
                    f"{message.subject[:50]}..."
                )

                # Trigger AI analysis task
                from app.tasks.ai_tasks import analyze_review
                analyze_review.delay(str(review.id))
                logger.info(f"Dispatched AI analysis task for review {review.id}")

            except Exception as e:
                error_msg = f"Failed to process message {message.message_id}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
                continue

        # Update last_checked_at
        account.last_checked_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            f"Completed check for {account.email}: "
            f"{new_emails} new emails from {total_fetched} fetched"
        )

        return {
            "success": True,
            "account_id": email_account_id,
            "email": account.email,
            "emails_fetched": total_fetched,
            "new_emails": new_emails,
            "errors": errors,
            "checked_at": account.last_checked_at.isoformat(),
        }

    except (GmailTemporaryError, GmailRateLimitError):
        # Let Celery handle retry
        raise

    except GmailAuthError as e:
        # Already handled above, but just in case
        logger.error(f"Unhandled OAuth error: {e}")
        return {
            "success": False,
            "error": str(e),
            "account_id": email_account_id,
        }

    except Exception as e:
        logger.error(f"Unexpected error checking emails for {email_account_id}: {e}")

        # Retry for unexpected errors
        try:
            raise self.retry(exc=e, countdown=60)
        except MaxRetriesExceededError:
            return {
                "success": False,
                "error": f"Max retries exceeded: {e}",
                "account_id": email_account_id,
            }

    finally:
        db.close()
