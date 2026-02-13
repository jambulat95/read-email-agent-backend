"""
API routes for analytics and statistics.

Endpoints:
- GET /api/analytics/summary - Summary statistics with period filter
- GET /api/analytics/trends - Trend data for charts
- GET /api/analytics/problems - Problems breakdown
- GET /api/analytics/response-time - Response time statistics
"""
import logging
from typing import List, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_active_user
from app.database import get_async_session
from app.models.user import User
from app.schemas.analytics import (
    AnalyticsSummary,
    ProblemStat,
    ResponseTimeStats,
    TrendPoint,
)
from app.services.analytics import AnalyticsService
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])

PeriodType = Literal["7d", "30d", "90d", "all"]


@router.get(
    "/summary",
    response_model=AnalyticsSummary,
    summary="Get analytics summary",
)
async def get_summary(
    period: PeriodType = Query("all", description="Time period for statistics"),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> AnalyticsSummary:
    service = AnalyticsService(db)
    return await service.get_summary(user.id, period)


@router.get(
    "/trends",
    response_model=List[TrendPoint],
    summary="Get trend data",
)
async def get_trends(
    period: PeriodType = Query("30d", description="Time period for trends"),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> List[TrendPoint]:
    service = AnalyticsService(db)
    return await service.get_trends(user.id, period)


@router.get(
    "/problems",
    response_model=List[ProblemStat],
    summary="Get problems breakdown",
)
async def get_problems_breakdown(
    period: PeriodType = Query("all", description="Time period for problems analysis"),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> List[ProblemStat]:
    service = AnalyticsService(db)
    return await service.get_problems_breakdown(user.id, period)


@router.get(
    "/response-time",
    response_model=ResponseTimeStats,
    summary="Get response time statistics",
)
async def get_response_time_stats(
    period: PeriodType = Query("all", description="Time period for statistics"),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> ResponseTimeStats:
    service = AnalyticsService(db)
    return await service.get_response_time_stats(user.id, period)
