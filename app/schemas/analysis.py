"""
Pydantic schemas for AI analysis results.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ReviewAnalysis(BaseModel):
    """Result of AI analysis for a review."""

    sentiment: Literal["positive", "negative", "neutral"] = Field(
        ...,
        description="Sentiment classification of the review",
    )
    priority: Literal["critical", "important", "normal"] = Field(
        ...,
        description="Priority level of the review",
    )
    summary: str = Field(
        ...,
        description="2-3 sentence summary of the review",
    )
    problems: List[str] = Field(
        default_factory=list,
        description="List of problems mentioned in the review",
    )
    suggestions: List[str] = Field(
        default_factory=list,
        description="List of suggestions from the customer",
    )
    customer_name: Optional[str] = Field(
        None,
        description="Extracted customer name if available",
    )
    requires_response: bool = Field(
        ...,
        description="Whether the review requires a response",
    )


class AnalysisState(BaseModel):
    """State object for LangGraph analysis workflow."""

    # Input
    review_text: str = ""
    subject: str = ""

    # Preprocessing
    cleaned_text: str = ""

    # Classification
    sentiment: Optional[Literal["positive", "negative", "neutral"]] = None

    # Extraction
    problems: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    customer_name: Optional[str] = None

    # Summary
    summary: str = ""

    # Priority
    priority: Optional[Literal["critical", "important", "normal"]] = None

    # Response decision
    requires_response: bool = False

    # Error tracking
    error: Optional[str] = None
    analysis_failed: bool = False
