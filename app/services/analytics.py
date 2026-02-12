"""
Analytics service for generating reports and statistics.

Includes Redis caching and comparison data.
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
    ComparisonData,
    ProblemStat,
    ProblemsBreakdownResponse,
    ResponseTimeStats,
    TopProblem,
    TrendPoint,
    TrendsResponse,
)
from app.services.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Cache TTL per period (seconds)
CACHE_TTL = {
    "day": 300,      # 5 minutes
    "week": 900,     # 15 minutes
    "month": 3600,   # 1 hour
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
        if period == "day":
            return now - timedelta(days=1)
        elif period == "week":
            return now - timedelta(weeks=1)
        elif period == "month":
            return now - timedelta(days=30)
        else:  # 'all'
            return None

    def _get_previous_date_range(self, period: str) -> tuple[Optional[datetime], Optional[datetime]]:
        """Get start/end date for the previous period (for comparison)."""
        now = datetime.utcnow()
        if period == "day":
            return now - timedelta(days=2), now - timedelta(days=1)
        elif period == "week":
            return now - timedelta(weeks=2), now - timedelta(weeks=1)
        elif period == "month":
            return now - timedelta(days=60), now - timedelta(days=30)
        else:
            return None, None

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

    async def _get_sentiment_counts(
        self, conditions: list
    ) -> Dict[str, int]:
        """Get sentiment counts for given conditions."""
        counts = {}
        for sentiment in [SentimentType.POSITIVE, SentimentType.NEGATIVE, SentimentType.NEUTRAL]:
            result = await self.db.execute(
                select(func.count(Review.id)).where(
                    and_(*conditions, Review.sentiment == sentiment.value)
                )
            )
            counts[sentiment.value] = result.scalar() or 0
        return counts

    async def _get_comparison(
        self, account_ids: List[UUID], period: str, current_total: int, current_sentiments: Dict[str, int]
    ) -> Optional[ComparisonData]:
        """Calculate comparison with previous period."""
        prev_start, prev_end = self._get_previous_date_range(period)
        if prev_start is None:
            return None

        prev_conditions = [
            Review.email_account_id.in_(account_ids),
            Review.received_at >= prev_start,
            Review.received_at < prev_end,
        ]

        prev_total = await self._count_by_conditions(prev_conditions)
        prev_sentiments = await self._get_sentiment_counts(prev_conditions)

        # Calculate changes
        total_change = current_total - prev_total
        total_change_percent = 0.0
        if prev_total > 0:
            total_change_percent = round((total_change / prev_total) * 100, 1)

        sentiment_change = {}
        for sentiment_key in ["positive", "negative", "neutral"]:
            curr = current_sentiments.get(sentiment_key, 0)
            prev = prev_sentiments.get(sentiment_key, 0)
            if prev > 0:
                change_pct = round(((curr - prev) / prev) * 100, 1)
            elif curr > 0:
                change_pct = 100.0
            else:
                change_pct = 0.0
            sentiment_change[sentiment_key] = change_pct

        return ComparisonData(
            total_change=total_change,
            total_change_percent=total_change_percent,
            sentiment_change=sentiment_change,
        )

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
            return AnalyticsSummary(
                total_reviews=0,
                positive=0,
                negative=0,
                neutral=0,
                unprocessed=0,
                critical_count=0,
                avg_response_time=None,
                top_problems=[],
                comparison=None,
            )

        start_date = self._get_date_range(period)

        conditions = [Review.email_account_id.in_(account_ids)]
        if start_date:
            conditions.append(Review.received_at >= start_date)

        total_reviews = await self._count_by_conditions(conditions)
        sentiment_counts = await self._get_sentiment_counts(conditions)

        # Unprocessed count
        unprocessed = await self._count_by_conditions(
            conditions + [Review.is_processed == False]
        )

        # Critical count
        critical_count = await self._count_by_conditions(
            conditions + [Review.priority == PriorityType.CRITICAL.value]
        )

        # Average response time
        avg_response_time = await self._compute_avg_response_time(conditions)

        # Top problems
        problems_result = await self.db.execute(
            select(Review.problems).where(
                and_(*conditions, Review.problems.isnot(None))
            )
        )
        all_problems: List[str] = []
        for row in problems_result.fetchall():
            if row[0]:
                all_problems.extend(row[0])

        problem_counter = Counter(all_problems)
        top_problems = [
            TopProblem(name=name, count=count)
            for name, count in problem_counter.most_common(5)
        ]

        # Comparison data
        comparison = await self._get_comparison(
            account_ids, period, total_reviews, sentiment_counts
        )

        return AnalyticsSummary(
            total_reviews=total_reviews,
            positive=sentiment_counts.get(SentimentType.POSITIVE.value, 0),
            negative=sentiment_counts.get(SentimentType.NEGATIVE.value, 0),
            neutral=sentiment_counts.get(SentimentType.NEUTRAL.value, 0),
            unprocessed=unprocessed,
            critical_count=critical_count,
            avg_response_time=avg_response_time,
            top_problems=top_problems,
            comparison=comparison,
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
        self, user_id: UUID, period: str = "month", group_by: str = "day"
    ) -> TrendsResponse:
        """Get trend data for charts with caching."""
        cache_key = f"analytics:trends:{user_id}:{period}:{group_by}"

        async def compute():
            return (await self._compute_trends(user_id, period, group_by)).model_dump()

        data = await get_cached_or_compute(cache_key, period, compute)

        if isinstance(data, dict):
            return TrendsResponse(**data)
        return data

    async def _compute_trends(
        self, user_id: UUID, period: str, group_by: str
    ) -> TrendsResponse:
        """Compute trend data (no cache)."""
        account_ids = await self._get_user_email_account_ids(user_id)
        if not account_ids:
            return TrendsResponse(data=[], period=period, group_by=group_by)

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
            if group_by == "week":
                date_key = (received_at - timedelta(days=received_at.weekday())).strftime("%Y-%m-%d")
            else:
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
        data_points = [
            TrendPoint(
                date=date_key,
                positive=date_data[date_key]["positive"],
                negative=date_data[date_key]["negative"],
                neutral=date_data[date_key]["neutral"],
                total=date_data[date_key]["total"],
            )
            for date_key in sorted_dates
        ]

        return TrendsResponse(data=data_points, period=period, group_by=group_by)

    async def get_problems_breakdown(
        self, user_id: UUID, period: str = "all"
    ) -> ProblemsBreakdownResponse:
        """Get breakdown of problems with trend data and caching."""
        cache_key = f"analytics:problems:{user_id}:{period}"

        async def compute():
            return (await self._compute_problems_breakdown(user_id, period)).model_dump()

        data = await get_cached_or_compute(cache_key, period, compute)

        if isinstance(data, dict):
            return ProblemsBreakdownResponse(**data)
        return data

    async def _compute_problems_breakdown(
        self, user_id: UUID, period: str
    ) -> ProblemsBreakdownResponse:
        """Compute problems breakdown with trend info (no cache)."""
        account_ids = await self._get_user_email_account_ids(user_id)
        if not account_ids:
            return ProblemsBreakdownResponse(
                problems=[], total_reviews_with_problems=0
            )

        start_date = self._get_date_range(period)
        conditions = [
            Review.email_account_id.in_(account_ids),
            Review.problems.isnot(None),
        ]
        if start_date:
            conditions.append(Review.received_at >= start_date)

        # Current period problems
        result = await self.db.execute(
            select(Review.problems).where(and_(*conditions))
        )
        rows = result.fetchall()

        all_problems: List[str] = []
        reviews_with_problems = 0
        for row in rows:
            if row[0] and len(row[0]) > 0:
                reviews_with_problems += 1
                all_problems.extend(row[0])

        if not all_problems:
            return ProblemsBreakdownResponse(
                problems=[], total_reviews_with_problems=0
            )

        # Previous period problems for trend calculation
        prev_start, prev_end = self._get_previous_date_range(period)
        prev_problem_counter: Counter = Counter()
        if prev_start is not None:
            prev_conditions = [
                Review.email_account_id.in_(account_ids),
                Review.problems.isnot(None),
                Review.received_at >= prev_start,
                Review.received_at < prev_end,
            ]
            prev_result = await self.db.execute(
                select(Review.problems).where(and_(*prev_conditions))
            )
            for row in prev_result.fetchall():
                if row[0]:
                    prev_problem_counter.update(row[0])

        problem_counter = Counter(all_problems)
        total_problems = len(all_problems)

        problems = []
        for name, count in problem_counter.most_common():
            prev_count = prev_problem_counter.get(name, 0)
            if prev_count == 0 and count > 0:
                trend = "up"
            elif count > prev_count:
                trend = "up"
            elif count < prev_count:
                trend = "down"
            else:
                trend = "stable"

            problems.append(
                ProblemStat(
                    name=name,
                    count=count,
                    percentage=round(count / total_problems * 100, 1),
                    trend=trend,
                )
            )

        return ProblemsBreakdownResponse(
            problems=problems, total_reviews_with_problems=reviews_with_problems
        )

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
