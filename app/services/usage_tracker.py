"""
Usage tracking service for plan limit enforcement.

Tracks monthly email processing counts per user via Redis
and validates against plan limits.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_account import EmailAccount
from app.models.enums import PlanType
from app.models.review import Review
from app.models.user import User
from app.services.plan_limits import PLAN_LIMITS
from app.services.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class UsageTracker:
    """Tracks resource usage and enforces plan limits."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_monthly_usage(self, user_id: UUID) -> int:
        """
        Get the number of reviews processed in the current month.

        First checks Redis cache, falls back to database query.
        """
        now = datetime.now(timezone.utc)
        cache_key = f"usage:{user_id}:{now.year}:{now.month}"

        try:
            redis = await get_redis_client()
            cached = await redis.get(cache_key)
            if cached is not None:
                return int(cached)
        except Exception:
            logger.warning("Redis unavailable for usage tracking, querying DB")

        # Query database
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        result = await self.db.execute(
            select(func.count(Review.id))
            .join(EmailAccount, Review.email_account_id == EmailAccount.id)
            .where(
                EmailAccount.user_id == user_id,
                Review.created_at >= month_start,
            )
        )
        count = result.scalar() or 0

        # Cache for 5 minutes
        try:
            redis = await get_redis_client()
            await redis.set(cache_key, count, ex=300)
        except Exception:
            pass

        return count

    async def check_limit(self, user: User) -> bool:
        """Check if the user has not exceeded their monthly email limit."""
        plan = PlanType(user.plan)
        limit = PLAN_LIMITS[plan]["emails_per_month"]
        usage = await self.get_monthly_usage(user.id)
        return usage < limit

    async def increment(self, user_id: UUID) -> None:
        """Increment the monthly usage counter in Redis."""
        now = datetime.now(timezone.utc)
        cache_key = f"usage:{user_id}:{now.year}:{now.month}"

        try:
            redis = await get_redis_client()
            pipe = redis.pipeline()
            pipe.incr(cache_key)
            pipe.expire(cache_key, 86400 * 35)  # Expire after ~1 month
            await pipe.execute()
        except Exception:
            logger.warning("Redis unavailable, usage increment skipped")

    async def get_email_accounts_count(self, user_id: UUID) -> int:
        """Get the number of connected email accounts for a user."""
        result = await self.db.execute(
            select(func.count(EmailAccount.id)).where(
                EmailAccount.user_id == user_id,
                EmailAccount.is_active == True,
            )
        )
        return result.scalar() or 0
