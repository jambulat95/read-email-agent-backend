"""Tests for AI analysis service."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.schemas.analysis import ReviewAnalysis, AnalysisState


class TestReviewAnalysisSchema:
    """Tests for ReviewAnalysis pydantic schema."""

    def test_valid_analysis(self):
        analysis = ReviewAnalysis(
            sentiment="negative",
            priority="critical",
            summary="Customer reports delivery issue",
            problems=["Late delivery", "Damaged package"],
            suggestions=["Offer refund"],
            customer_name="John Doe",
            requires_response=True,
        )
        assert analysis.sentiment == "negative"
        assert analysis.priority == "critical"
        assert len(analysis.problems) == 2
        assert analysis.requires_response is True

    def test_minimal_analysis(self):
        analysis = ReviewAnalysis(
            sentiment="positive",
            priority="normal",
            summary="Customer is happy",
            requires_response=False,
        )
        assert analysis.problems == []
        assert analysis.suggestions == []
        assert analysis.customer_name is None

    def test_invalid_sentiment(self):
        with pytest.raises(Exception):
            ReviewAnalysis(
                sentiment="unknown",
                priority="normal",
                summary="Test",
                requires_response=False,
            )

    def test_invalid_priority(self):
        with pytest.raises(Exception):
            ReviewAnalysis(
                sentiment="positive",
                priority="urgent",
                summary="Test",
                requires_response=False,
            )


class TestAnalysisState:
    """Tests for AnalysisState model."""

    def test_default_state(self):
        state = AnalysisState()
        assert state.review_text == ""
        assert state.sentiment is None
        assert state.problems == []
        assert state.analysis_failed is False

    def test_state_with_data(self):
        state = AnalysisState(
            review_text="Great product!",
            subject="Feedback",
            sentiment="positive",
            priority="normal",
            summary="Positive feedback",
        )
        assert state.review_text == "Great product!"
        assert state.sentiment == "positive"
