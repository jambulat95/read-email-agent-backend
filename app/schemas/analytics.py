"""
Pydantic schemas for analytics API.
"""
from datetime import date
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class TopProblem(BaseModel):
    """Schema for top problem item."""

    name: str = Field(..., description="Problem name/description")
    count: int = Field(..., description="Number of occurrences", ge=0)


class ComparisonData(BaseModel):
    """Schema for comparison with previous period."""

    total_change: int = Field(0, description="Absolute change in total reviews")
    total_change_percent: float = Field(0.0, description="Percentage change in total reviews")
    sentiment_change: Dict[str, float] = Field(
        default_factory=dict,
        description="Percentage change per sentiment (e.g. {'positive': 5.0, 'negative': -3.0})",
    )


class AnalyticsSummary(BaseModel):
    """Schema for analytics summary response."""

    total_reviews: int = Field(..., description="Total number of reviews", ge=0)
    positive: int = Field(..., description="Number of positive reviews", ge=0)
    negative: int = Field(..., description="Number of negative reviews", ge=0)
    neutral: int = Field(..., description="Number of neutral reviews", ge=0)
    unprocessed: int = Field(..., description="Number of unprocessed reviews", ge=0)
    critical_count: int = Field(..., description="Number of critical priority reviews", ge=0)
    avg_response_time: Optional[float] = Field(
        None, description="Average response time in hours"
    )
    top_problems: List[TopProblem] = Field(
        default_factory=list, description="Most common problems"
    )
    comparison: Optional[ComparisonData] = Field(
        None, description="Comparison with previous period"
    )


class TrendPoint(BaseModel):
    """Schema for a single trend data point."""

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    positive: int = Field(0, description="Number of positive reviews", ge=0)
    negative: int = Field(0, description="Number of negative reviews", ge=0)
    neutral: int = Field(0, description="Number of neutral reviews", ge=0)
    total: int = Field(0, description="Total reviews for this period", ge=0)


class TrendsResponse(BaseModel):
    """Schema for trends response."""

    data: List[TrendPoint] = Field(..., description="Trend data points")
    period: str = Field(..., description="Time period (day/week/month/all)")
    group_by: str = Field(..., description="Grouping (day/week)")


class ProblemStat(BaseModel):
    """Schema for problem statistics."""

    name: str = Field(..., description="Problem name/description")
    count: int = Field(..., description="Number of occurrences", ge=0)
    percentage: float = Field(..., description="Percentage of total", ge=0, le=100)
    trend: str = Field("stable", description="Trend direction: up, down, stable")


class ProblemsBreakdownResponse(BaseModel):
    """Schema for problems breakdown response."""

    problems: List[ProblemStat] = Field(..., description="Problems statistics")
    total_reviews_with_problems: int = Field(
        ..., description="Total reviews with at least one problem", ge=0
    )


class ResponseTimeStats(BaseModel):
    """Schema for response time statistics."""

    avg_hours: Optional[float] = Field(None, description="Average response time in hours")
    min_hours: Optional[float] = Field(None, description="Minimum response time in hours")
    max_hours: Optional[float] = Field(None, description="Maximum response time in hours")
    processed_count: int = Field(0, description="Number of processed reviews")
    total_count: int = Field(0, description="Total number of reviews")
