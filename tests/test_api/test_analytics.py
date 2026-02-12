"""Tests for analytics API endpoints."""
import pytest
from unittest.mock import patch, AsyncMock

from httpx import AsyncClient

from app.models.review import Review
from app.models.email_account import EmailAccount


class TestAnalyticsSummary:
    """Tests for GET /api/analytics/summary."""

    async def test_summary_empty(
        self,
        client: AsyncClient,
        auth_headers: dict,
        email_account: EmailAccount,
    ):
        """Summary with no reviews returns zeros."""
        with patch("app.services.analytics.get_redis_client", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value.get = AsyncMock(return_value=None)
            mock_redis.return_value.setex = AsyncMock()

            response = await client.get(
                "/api/analytics/summary", headers=auth_headers
            )
        assert response.status_code == 200
        data = response.json()
        assert data["total_reviews"] == 0
        assert data["positive"] == 0
        assert data["negative"] == 0

    async def test_summary_with_reviews(
        self,
        client: AsyncClient,
        auth_headers: dict,
        multiple_reviews: list[Review],
    ):
        """Summary with reviews returns correct counts."""
        with patch("app.services.analytics.get_redis_client", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value.get = AsyncMock(return_value=None)
            mock_redis.return_value.setex = AsyncMock()

            response = await client.get(
                "/api/analytics/summary?period=all", headers=auth_headers
            )
        assert response.status_code == 200
        data = response.json()
        assert data["total_reviews"] == 5
        assert data["positive"] == 2
        assert data["negative"] == 2
        assert data["neutral"] == 1

    async def test_summary_unauthorized(self, client: AsyncClient):
        response = await client.get("/api/analytics/summary")
        assert response.status_code == 401


class TestAnalyticsTrends:
    """Tests for GET /api/analytics/trends."""

    async def test_trends_empty(
        self,
        client: AsyncClient,
        auth_headers: dict,
        email_account: EmailAccount,
    ):
        with patch("app.services.analytics.get_redis_client", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value.get = AsyncMock(return_value=None)
            mock_redis.return_value.setex = AsyncMock()

            response = await client.get(
                "/api/analytics/trends", headers=auth_headers
            )
        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []

    async def test_trends_with_reviews(
        self,
        client: AsyncClient,
        auth_headers: dict,
        multiple_reviews: list[Review],
    ):
        with patch("app.services.analytics.get_redis_client", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value.get = AsyncMock(return_value=None)
            mock_redis.return_value.setex = AsyncMock()

            response = await client.get(
                "/api/analytics/trends?period=all&group_by=day",
                headers=auth_headers,
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) > 0
        assert data["period"] == "all"
        assert data["group_by"] == "day"


class TestProblemsBreakdown:
    """Tests for GET /api/analytics/problems."""

    async def test_problems_empty(
        self,
        client: AsyncClient,
        auth_headers: dict,
        email_account: EmailAccount,
    ):
        with patch("app.services.analytics.get_redis_client", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value.get = AsyncMock(return_value=None)
            mock_redis.return_value.setex = AsyncMock()

            response = await client.get(
                "/api/analytics/problems", headers=auth_headers
            )
        assert response.status_code == 200
        data = response.json()
        assert data["problems"] == []

    async def test_problems_with_reviews(
        self,
        client: AsyncClient,
        auth_headers: dict,
        multiple_reviews: list[Review],
    ):
        with patch("app.services.analytics.get_redis_client", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value.get = AsyncMock(return_value=None)
            mock_redis.return_value.setex = AsyncMock()

            response = await client.get(
                "/api/analytics/problems?period=all", headers=auth_headers
            )
        assert response.status_code == 200
        data = response.json()
        assert data["total_reviews_with_problems"] >= 0


class TestResponseTime:
    """Tests for GET /api/analytics/response-time."""

    async def test_response_time_stats(
        self,
        client: AsyncClient,
        auth_headers: dict,
        multiple_reviews: list[Review],
    ):
        with patch("app.services.analytics.get_redis_client", new_callable=AsyncMock) as mock_redis:
            mock_redis.return_value.get = AsyncMock(return_value=None)
            mock_redis.return_value.setex = AsyncMock()

            response = await client.get(
                "/api/analytics/response-time", headers=auth_headers
            )
        assert response.status_code == 200
        data = response.json()
        assert "processed_count" in data
        assert "total_count" in data
