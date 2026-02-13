"""
Pydantic schemas for analytics API.
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AnalyticsSummary(BaseModel):
    """Schema for analytics summary response."""

    total_reviews: int = Field(0, description="Total number of reviews", ge=0)
    positive_reviews: int = Field(0, description="Number of positive reviews", ge=0)
    negative_reviews: int = Field(0, description="Number of negative reviews", ge=0)
    neutral_reviews: int = Field(0, description="Number of neutral reviews", ge=0)
    mixed_reviews: int = Field(0, description="Number of mixed reviews", ge=0)
    critical_count: int = Field(0, description="Number of critical priority reviews", ge=0)
    high_count: int = Field(0, description="Number of high priority reviews", ge=0)
    medium_count: int = Field(0, description="Number of medium priority reviews", ge=0)
    low_count: int = Field(0, description="Number of low priority reviews", ge=0)
    avg_response_time_hours: Optional[float] = Field(
        None, description="Average response time in hours"
    )
    processed_count: int = Field(0, description="Number of processed reviews", ge=0)
    unprocessed_count: int = Field(0, description="Number of unprocessed reviews", ge=0)


class TrendPoint(BaseModel):
    """Schema for a single trend data point."""

    date: str = Field(..., description="Date in YYYY-MM-DD format")
    positive: int = Field(0, description="Number of positive reviews", ge=0)
    negative: int = Field(0, description="Number of negative reviews", ge=0)
    neutral: int = Field(0, description="Number of neutral reviews", ge=0)
    total: int = Field(0, description="Total reviews for this period", ge=0)


class ProblemStat(BaseModel):
    """Schema for problem statistics."""

    problem: str = Field(..., description="Problem name/description")
    count: int = Field(..., description="Number of occurrences", ge=0)
    percentage: float = Field(..., description="Percentage of total", ge=0, le=100)


class ResponseTimeStats(BaseModel):
    """Schema for response time statistics."""

    avg_hours: Optional[float] = Field(None, description="Average response time in hours")
    min_hours: Optional[float] = Field(None, description="Minimum response time in hours")
    max_hours: Optional[float] = Field(None, description="Maximum response time in hours")
    processed_count: int = Field(0, description="Number of processed reviews")
    total_count: int = Field(0, description="Total number of reviews")
