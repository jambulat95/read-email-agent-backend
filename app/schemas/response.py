"""
Pydantic schemas for draft response operations.
"""
from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DraftResponseCreate(BaseModel):
    """Schema for creating a draft response."""

    content: str = Field(
        ...,
        description="Generated response content",
        min_length=1,
        max_length=5000,
    )
    tone: Literal["formal", "friendly", "professional"] = Field(
        ...,
        description="Tone of the response",
    )
    variant_number: int = Field(
        ...,
        description="Variant number (1, 2, or 3)",
        ge=1,
        le=3,
    )


class DraftResponseResponse(BaseModel):
    """Schema for draft response in API responses."""

    id: UUID = Field(..., description="Draft response ID")
    review_id: UUID = Field(..., description="Associated review ID")
    content: str = Field(..., description="Response content")
    tone: str = Field(..., description="Response tone")
    variant_number: int = Field(..., description="Variant number")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = {"from_attributes": True}


class DraftResponseListResponse(BaseModel):
    """Schema for list of draft responses."""

    drafts: List[DraftResponseResponse] = Field(
        default_factory=list,
        description="List of draft responses",
    )
    total: int = Field(..., description="Total number of drafts")


class RegenerateRequest(BaseModel):
    """Schema for regeneration request."""

    tone: Optional[Literal["formal", "friendly", "professional"]] = Field(
        None,
        description="Override tone for regeneration (optional)",
    )
