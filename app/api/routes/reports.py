"""
API routes for weekly reports.

Endpoints:
- GET /api/reports/weekly - List weekly reports
- GET /api/reports/weekly/{id} - Report details
- GET /api/reports/weekly/{id}/pdf - Download PDF
- POST /api/reports/weekly/generate - Force generate report
"""
import logging
import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_plan
from app.database import get_async_session
from app.models.enums import PlanType
from app.models.user import User
from app.models.weekly_report import WeeklyReport
from app.schemas.reports import (
    GenerateReportResponse,
    WeeklyReportDetail,
    WeeklyReportListResponse,
    WeeklyReportSummary,
)
from app.services.weekly_report import WeeklyReportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/weekly",
    response_model=WeeklyReportListResponse,
    summary="List weekly reports",
    description="Returns paginated list of weekly reports for the current user. Requires PRO or ENTERPRISE plan.",
)
async def list_weekly_reports(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=50, description="Items per page"),
    user: User = Depends(require_plan(PlanType.PROFESSIONAL)),
    db: AsyncSession = Depends(get_async_session),
) -> WeeklyReportListResponse:
    """List weekly reports for the current user."""
    offset = (page - 1) * page_size

    # Count total
    count_result = await db.execute(
        select(func.count(WeeklyReport.id)).where(
            WeeklyReport.user_id == user.id
        )
    )
    total = count_result.scalar() or 0

    # Get reports
    result = await db.execute(
        select(WeeklyReport)
        .where(WeeklyReport.user_id == user.id)
        .order_by(WeeklyReport.week_start.desc())
        .offset(offset)
        .limit(page_size)
    )
    reports = result.scalars().all()

    return WeeklyReportListResponse(
        reports=[
            WeeklyReportSummary(
                id=r.id,
                week_start=r.week_start,
                week_end=r.week_end,
                total_reviews=r.total_reviews,
                sentiment_breakdown=r.sentiment_breakdown,
                total_change_percent=r.total_change_percent,
                sent_at=r.sent_at,
                created_at=r.created_at,
            )
            for r in reports
        ],
        total=total,
    )


@router.get(
    "/weekly/{report_id}",
    response_model=WeeklyReportDetail,
    summary="Get report details",
    description="Returns full details of a specific weekly report.",
)
async def get_weekly_report(
    report_id: UUID,
    user: User = Depends(require_plan(PlanType.PROFESSIONAL)),
    db: AsyncSession = Depends(get_async_session),
) -> WeeklyReportDetail:
    """Get details of a specific weekly report."""
    result = await db.execute(
        select(WeeklyReport).where(
            and_(
                WeeklyReport.id == report_id,
                WeeklyReport.user_id == user.id,
            )
        )
    )
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    return WeeklyReportDetail(
        id=report.id,
        user_id=report.user_id,
        week_start=report.week_start,
        week_end=report.week_end,
        total_reviews=report.total_reviews,
        sentiment_breakdown=report.sentiment_breakdown,
        top_problems=report.top_problems,
        critical_reviews=report.critical_reviews,
        total_change_percent=report.total_change_percent,
        sentiment_change=report.sentiment_change,
        recommendations=report.recommendations,
        sent_at=report.sent_at,
        pdf_url=report.pdf_url,
        created_at=report.created_at,
    )


@router.get(
    "/weekly/{report_id}/pdf",
    summary="Download report PDF",
    description="Download the PDF version of a weekly report.",
)
async def download_weekly_report_pdf(
    report_id: UUID,
    user: User = Depends(require_plan(PlanType.PROFESSIONAL)),
    db: AsyncSession = Depends(get_async_session),
):
    """Download PDF for a weekly report."""
    result = await db.execute(
        select(WeeklyReport).where(
            and_(
                WeeklyReport.id == report_id,
                WeeklyReport.user_id == user.id,
            )
        )
    )
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    # Generate PDF if not exists
    if not report.pdf_url or not os.path.exists(report.pdf_url):
        service = WeeklyReportService(db)
        pdf_path = await service.generate_pdf(report)
    else:
        pdf_path = report.pdf_url

    if not os.path.exists(pdf_path):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate PDF",
        )

    filename = f"report_{report.week_start}_{report.week_end}.pdf"
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=filename,
    )


@router.post(
    "/weekly/generate",
    response_model=GenerateReportResponse,
    summary="Force generate weekly report",
    description="Manually trigger generation of a weekly report for the previous week.",
)
async def generate_weekly_report(
    user: User = Depends(require_plan(PlanType.PROFESSIONAL)),
    db: AsyncSession = Depends(get_async_session),
) -> GenerateReportResponse:
    """Force generate a weekly report."""
    service = WeeklyReportService(db)

    try:
        report = await service.generate_report(user.id)
        return GenerateReportResponse(
            report_id=report.id,
            message="Report generated successfully",
        )
    except Exception as e:
        logger.error(f"Error generating report for user {user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate report: {str(e)}",
        )
