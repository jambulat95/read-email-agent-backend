"""
Pydantic schemas for weekly reports API.
"""
from datetime import date, datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class WeeklyReportSummary(BaseModel):
    """Schema for weekly report list item."""

    id: UUID = Field(..., description="Report UUID")
    week_start: date = Field(..., description="Week start date (Monday)")
    week_end: date = Field(..., description="Week end date (Sunday)")
    total_reviews: int = Field(..., description="Total reviews in the week")
    sentiment_breakdown: Optional[Dict[str, int]] = Field(
        None, description="Sentiment counts"
    )
    total_change_percent: Optional[float] = Field(
        None, description="Change vs previous week (%)"
    )
    sent_at: Optional[datetime] = Field(None, description="When the report was sent")
    created_at: datetime = Field(..., description="When the report was created")


class WeeklyReportDetail(BaseModel):
    """Schema for weekly report detail."""

    id: UUID
    user_id: UUID
    week_start: date
    week_end: date
    total_reviews: int
    sentiment_breakdown: Optional[Dict[str, int]] = None
    top_problems: Optional[List[Dict]] = None
    critical_reviews: Optional[List[str]] = None
    total_change_percent: Optional[float] = None
    sentiment_change: Optional[Dict[str, float]] = None
    recommendations: Optional[List[str]] = None
    sent_at: Optional[datetime] = None
    pdf_url: Optional[str] = None
    created_at: datetime


class WeeklyReportListResponse(BaseModel):
    """Schema for paginated list of weekly reports."""

    reports: List[WeeklyReportSummary] = Field(..., description="List of reports")
    total: int = Field(..., description="Total number of reports")


class GenerateReportResponse(BaseModel):
    """Schema for report generation result."""

    report_id: UUID
    message: str = "Report generated successfully"
