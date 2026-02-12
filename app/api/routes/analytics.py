"""
API routes for analytics and statistics.

Endpoints:
- GET /api/analytics/summary - Summary statistics with period filter
- GET /api/analytics/trends - Trend data for charts
- GET /api/analytics/problems - Problems breakdown
"""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_active_user
from app.database import get_async_session
from app.models.user import User
from app.schemas.analytics import (
    AnalyticsSummary,
    ProblemsBreakdownResponse,
    ResponseTimeStats,
    TrendsResponse,
)
from app.services.analytics import AnalyticsService
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get(
    "/summary",
    response_model=AnalyticsSummary,
    summary="Get analytics summary",
    description="Returns summary statistics for reviews including sentiment counts, priority breakdown, and top problems.",
)
async def get_summary(
    period: Literal["day", "week", "month", "all"] = Query(
        "all", description="Time period for statistics"
    ),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> AnalyticsSummary:
    """
    Get summary analytics.

    Args:
        period: Time period ('day', 'week', 'month', 'all')
        user: Current authenticated user
        db: Database session

    Returns:
        Summary statistics
    """
    service = AnalyticsService(db)
    return await service.get_summary(user.id, period)


@router.get(
    "/trends",
    response_model=TrendsResponse,
    summary="Get trend data",
    description="Returns trend data for charts showing review counts over time by sentiment.",
)
async def get_trends(
    period: Literal["week", "month", "all"] = Query(
        "month", description="Time period for trends"
    ),
    group_by: Literal["day", "week"] = Query(
        "day", description="Grouping interval"
    ),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> TrendsResponse:
    """
    Get trend data for charts.

    Args:
        period: Time period ('week', 'month', 'all')
        group_by: Grouping interval ('day', 'week')
        user: Current authenticated user
        db: Database session

    Returns:
        Trend data points
    """
    service = AnalyticsService(db)
    return await service.get_trends(user.id, period, group_by)


@router.get(
    "/problems",
    response_model=ProblemsBreakdownResponse,
    summary="Get problems breakdown",
    description="Returns breakdown of problems identified in reviews with counts and percentages.",
)
async def get_problems_breakdown(
    period: Literal["day", "week", "month", "all"] = Query(
        "all", description="Time period for problems analysis"
    ),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> ProblemsBreakdownResponse:
    """
    Get problems breakdown.

    Args:
        period: Time period ('day', 'week', 'month', 'all')
        user: Current authenticated user
        db: Database session

    Returns:
        Problems statistics
    """
    service = AnalyticsService(db)
    return await service.get_problems_breakdown(user.id, period)


@router.get(
    "/response-time",
    response_model=ResponseTimeStats,
    summary="Get response time statistics",
    description="Returns statistics about review processing times.",
)
async def get_response_time_stats(
    period: Literal["day", "week", "month", "all"] = Query(
        "all", description="Time period for statistics"
    ),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> ResponseTimeStats:
    """Get response time statistics."""
    service = AnalyticsService(db)
    return await service.get_response_time_stats(user.id, period)
