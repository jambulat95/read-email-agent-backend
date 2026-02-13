"""
Analytics service for generating reports and statistics.

Includes Redis caching.
"""
import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_account import EmailAccount
from app.models.enums import PriorityType, SentimentType
from app.models.review import Review
from app.schemas.analytics import (
    AnalyticsSummary,
    ProblemStat,
    ResponseTimeStats,
    TrendPoint,
)
from app.services.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Cache TTL per period (seconds)
CACHE_TTL = {
    "7d": 300,       # 5 minutes
    "30d": 900,      # 15 minutes
    "90d": 3600,     # 1 hour
    "all": 3600,     # 1 hour
}


async def get_cached_or_compute(
    cache_key: str,
    period: str,
    compute_fn: Callable,
) -> Any:
    """
    Get data from Redis cache or compute and store it.

    Args:
        cache_key: Redis key for caching
        period: Period string for TTL lookup
        compute_fn: Async function to compute data if cache miss

    Returns:
        Cached or computed data (dict)
    """
    try:
        redis = await get_redis_client()
        cached = await redis.get(cache_key)
        if cached:
            logger.debug(f"Cache hit for {cache_key}")
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"Redis cache read error: {e}")

    result = await compute_fn()

    try:
        redis = await get_redis_client()
        ttl = CACHE_TTL.get(period, 900)
        await redis.setex(cache_key, ttl, json.dumps(result, default=str))
        logger.debug(f"Cached {cache_key} with TTL {ttl}s")
    except Exception as e:
        logger.warning(f"Redis cache write error: {e}")

    return result


class AnalyticsService:
    """Service for generating analytics and reports."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_date_range(self, period: str) -> Optional[datetime]:
        """Get start date for a given period."""
        now = datetime.utcnow()
        if period == "7d":
            return now - timedelta(days=7)
        elif period == "30d":
            return now - timedelta(days=30)
        elif period == "90d":
            return now - timedelta(days=90)
        else:  # 'all'
            return None

    async def _get_user_email_account_ids(self, user_id: UUID) -> List[UUID]:
        """Get all email account IDs for a user."""
        result = await self.db.execute(
            select(EmailAccount.id).where(EmailAccount.user_id == user_id)
        )
        return [row[0] for row in result.fetchall()]

    async def _count_by_conditions(self, conditions: list) -> int:
        """Count reviews matching conditions."""
        result = await self.db.execute(
            select(func.count(Review.id)).where(and_(*conditions))
        )
        return result.scalar() or 0

    async def get_summary(
        self, user_id: UUID, period: str = "all"
    ) -> AnalyticsSummary:
        """Get summary analytics for a user with caching."""
        cache_key = f"analytics:summary:{user_id}:{period}"

        async def compute():
            return (await self._compute_summary(user_id, period)).model_dump()

        data = await get_cached_or_compute(cache_key, period, compute)

        if isinstance(data, dict):
            return AnalyticsSummary(**data)
        return data

    async def _compute_summary(
        self, user_id: UUID, period: str
    ) -> AnalyticsSummary:
        """Compute summary analytics (no cache)."""
        account_ids = await self._get_user_email_account_ids(user_id)
        if not account_ids:
            return AnalyticsSummary()

        start_date = self._get_date_range(period)

        conditions = [Review.email_account_id.in_(account_ids)]
        if start_date:
            conditions.append(Review.received_at >= start_date)

        total_reviews = await self._count_by_conditions(conditions)

        # Sentiment counts
        positive = await self._count_by_conditions(
            conditions + [Review.sentiment == SentimentType.POSITIVE.value]
        )
        negative = await self._count_by_conditions(
            conditions + [Review.sentiment == SentimentType.NEGATIVE.value]
        )
        neutral = await self._count_by_conditions(
            conditions + [Review.sentiment == SentimentType.NEUTRAL.value]
        )
        mixed = await self._count_by_conditions(
            conditions + [Review.sentiment == "mixed"]
        )

        # Priority counts (backend: critical/important/normal → frontend: critical/high/medium/low)
        critical_count = await self._count_by_conditions(
            conditions + [Review.priority == PriorityType.CRITICAL.value]
        )
        high_count = await self._count_by_conditions(
            conditions + [Review.priority == PriorityType.IMPORTANT.value]
        )
        medium_count = await self._count_by_conditions(
            conditions + [Review.priority == PriorityType.NORMAL.value]
        )
        low_count = 0

        # Processed / unprocessed
        processed = await self._count_by_conditions(
            conditions + [Review.is_processed == True]
        )
        unprocessed = await self._count_by_conditions(
            conditions + [Review.is_processed == False]
        )

        # Average response time
        avg_response_time = await self._compute_avg_response_time(conditions)

        return AnalyticsSummary(
            total_reviews=total_reviews,
            positive_reviews=positive,
            negative_reviews=negative,
            neutral_reviews=neutral,
            mixed_reviews=mixed,
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            avg_response_time_hours=avg_response_time,
            processed_count=processed,
            unprocessed_count=unprocessed,
        )

    async def _compute_avg_response_time(self, conditions: list) -> Optional[float]:
        """Compute average response time in hours for processed reviews."""
        result = await self.db.execute(
            select(
                func.avg(
                    extract("epoch", Review.processed_at - Review.received_at) / 3600
                )
            ).where(
                and_(
                    *conditions,
                    Review.is_processed == True,
                    Review.processed_at.isnot(None),
                )
            )
        )
        avg_val = result.scalar()
        return round(float(avg_val), 1) if avg_val is not None else None

    async def get_trends(
        self, user_id: UUID, period: str = "30d"
    ) -> List[TrendPoint]:
        """Get trend data for charts with caching."""
        cache_key = f"analytics:trends:{user_id}:{period}"

        async def compute():
            points = await self._compute_trends(user_id, period)
            return [p.model_dump() for p in points]

        data = await get_cached_or_compute(cache_key, period, compute)

        if isinstance(data, list):
            return [TrendPoint(**d) if isinstance(d, dict) else d for d in data]
        return data

    async def _compute_trends(
        self, user_id: UUID, period: str
    ) -> List[TrendPoint]:
        """Compute trend data (no cache)."""
        account_ids = await self._get_user_email_account_ids(user_id)
        if not account_ids:
            return []

        start_date = self._get_date_range(period)
        conditions = [Review.email_account_id.in_(account_ids)]
        if start_date:
            conditions.append(Review.received_at >= start_date)

        result = await self.db.execute(
            select(Review.received_at, Review.sentiment).where(and_(*conditions))
        )
        reviews = result.fetchall()

        date_data: dict = {}
        for received_at, sentiment in reviews:
            date_key = received_at.strftime("%Y-%m-%d")

            if date_key not in date_data:
                date_data[date_key] = {"positive": 0, "negative": 0, "neutral": 0, "total": 0}

            date_data[date_key]["total"] += 1
            if sentiment == SentimentType.POSITIVE.value:
                date_data[date_key]["positive"] += 1
            elif sentiment == SentimentType.NEGATIVE.value:
                date_data[date_key]["negative"] += 1
            elif sentiment == SentimentType.NEUTRAL.value:
                date_data[date_key]["neutral"] += 1

        sorted_dates = sorted(date_data.keys())
        return [
            TrendPoint(
                date=date_key,
                positive=date_data[date_key]["positive"],
                negative=date_data[date_key]["negative"],
                neutral=date_data[date_key]["neutral"],
                total=date_data[date_key]["total"],
            )
            for date_key in sorted_dates
        ]

    async def get_problems_breakdown(
        self, user_id: UUID, period: str = "all"
    ) -> List[ProblemStat]:
        """Get breakdown of problems with caching."""
        cache_key = f"analytics:problems:{user_id}:{period}"

        async def compute():
            stats = await self._compute_problems_breakdown(user_id, period)
            return [s.model_dump() for s in stats]

        data = await get_cached_or_compute(cache_key, period, compute)

        if isinstance(data, list):
            return [ProblemStat(**d) if isinstance(d, dict) else d for d in data]
        return data

    async def _compute_problems_breakdown(
        self, user_id: UUID, period: str
    ) -> List[ProblemStat]:
        """Compute problems breakdown (no cache)."""
        account_ids = await self._get_user_email_account_ids(user_id)
        if not account_ids:
            return []

        start_date = self._get_date_range(period)
        conditions = [
            Review.email_account_id.in_(account_ids),
            Review.problems.isnot(None),
        ]
        if start_date:
            conditions.append(Review.received_at >= start_date)

        result = await self.db.execute(
            select(Review.problems).where(and_(*conditions))
        )
        rows = result.fetchall()

        all_problems: List[str] = []
        for row in rows:
            if row[0] and len(row[0]) > 0:
                all_problems.extend(row[0])

        if not all_problems:
            return []

        problem_counter = Counter(all_problems)
        total_problems = len(all_problems)

        return [
            ProblemStat(
                problem=name,
                count=count,
                percentage=round(count / total_problems * 100, 1),
            )
            for name, count in problem_counter.most_common()
        ]

    async def get_response_time_stats(
        self, user_id: UUID, period: str = "all"
    ) -> ResponseTimeStats:
        """Get response time statistics."""
        cache_key = f"analytics:response_time:{user_id}:{period}"

        async def compute():
            return (await self._compute_response_time_stats(user_id, period)).model_dump()

        data = await get_cached_or_compute(cache_key, period, compute)

        if isinstance(data, dict):
            return ResponseTimeStats(**data)
        return data

    async def _compute_response_time_stats(
        self, user_id: UUID, period: str
    ) -> ResponseTimeStats:
        """Compute response time stats (no cache)."""
        account_ids = await self._get_user_email_account_ids(user_id)
        if not account_ids:
            return ResponseTimeStats()

        start_date = self._get_date_range(period)
        conditions = [Review.email_account_id.in_(account_ids)]
        if start_date:
            conditions.append(Review.received_at >= start_date)

        total_count = await self._count_by_conditions(conditions)

        processed_conditions = conditions + [
            Review.is_processed == True,
            Review.processed_at.isnot(None),
        ]
        processed_count = await self._count_by_conditions(processed_conditions)

        if processed_count == 0:
            return ResponseTimeStats(
                total_count=total_count,
                processed_count=0,
            )

        time_expr = extract("epoch", Review.processed_at - Review.received_at) / 3600

        result = await self.db.execute(
            select(
                func.avg(time_expr),
                func.min(time_expr),
                func.max(time_expr),
            ).where(and_(*processed_conditions))
        )
        row = result.one()

        return ResponseTimeStats(
            avg_hours=round(float(row[0]), 1) if row[0] is not None else None,
            min_hours=round(float(row[1]), 1) if row[1] is not None else None,
            max_hours=round(float(row[2]), 1) if row[2] is not None else None,
            processed_count=processed_count,
            total_count=total_count,
        )
