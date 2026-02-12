"""
Pydantic schemas for reviews API.
"""
from datetime import datetime
from typing import Generic, List, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.response import DraftResponseResponse


T = TypeVar("T")


class ReviewListItem(BaseModel):
    """Schema for review in list responses."""

    id: UUID = Field(..., description="Review unique identifier")
    sender_email: str = Field(..., description="Sender email address")
    sender_name: Optional[str] = Field(None, description="Sender name if available")
    subject: str = Field(..., description="Email subject")
    sentiment: Optional[str] = Field(None, description="Detected sentiment (positive/negative/neutral)")
    priority: Optional[str] = Field(None, description="Priority level (critical/important/normal)")
    summary: Optional[str] = Field(None, description="AI-generated summary")
    problems: List[str] = Field(default_factory=list, description="Identified problems")
    is_processed: bool = Field(..., description="Whether review has been analyzed")
    received_at: datetime = Field(..., description="When the email was received")
    notes: Optional[str] = Field(None, description="User notes")

    model_config = {"from_attributes": True}


class ReviewDetail(ReviewListItem):
    """Schema for detailed review response."""

    suggestions: List[str] = Field(default_factory=list, description="AI suggestions for response")
    drafts: List[DraftResponseResponse] = Field(
        default_factory=list, description="Generated draft responses"
    )
    email_account_email: str = Field(..., description="Email account this review belongs to")
    created_at: datetime = Field(..., description="When the review was created in system")
    processed_at: Optional[datetime] = Field(None, description="When the review was analyzed")


class ReviewUpdate(BaseModel):
    """Schema for updating a review."""

    is_processed: Optional[bool] = Field(None, description="Mark as processed/unprocessed")
    notes: Optional[str] = Field(None, description="User notes for the review", max_length=5000)


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response schema."""

    items: List[T] = Field(..., description="List of items")
    total: int = Field(..., description="Total number of items", ge=0)
    page: int = Field(..., description="Current page number", ge=1)
    per_page: int = Field(..., description="Items per page", ge=1, le=100)
    pages: int = Field(..., description="Total number of pages", ge=0)


class ReviewListResponse(PaginatedResponse[ReviewListItem]):
    """Paginated response for reviews list."""

    pass
