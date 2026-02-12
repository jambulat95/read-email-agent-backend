"""Tests for reviews API endpoints."""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.models.email_account import EmailAccount
from app.models.review import Review
from app.models.draft_response import DraftResponse
from app.models.user import User


class TestListReviews:
    """Tests for GET /api/reviews."""

    async def test_list_reviews_empty(
        self,
        client: AsyncClient,
        auth_headers: dict,
        email_account: EmailAccount,
    ):
        response = await client.get("/api/reviews", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_reviews_with_data(
        self,
        client: AsyncClient,
        auth_headers: dict,
        multiple_reviews: list[Review],
    ):
        response = await client.get("/api/reviews", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["items"]) == 5

    async def test_list_reviews_pagination(
        self,
        client: AsyncClient,
        auth_headers: dict,
        multiple_reviews: list[Review],
    ):
        response = await client.get(
            "/api/reviews?page=1&per_page=2", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["pages"] == 3

    async def test_list_reviews_filter_sentiment(
        self,
        client: AsyncClient,
        auth_headers: dict,
        multiple_reviews: list[Review],
    ):
        response = await client.get(
            "/api/reviews?sentiment=negative", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        for item in data["items"]:
            assert item["sentiment"] == "negative"

    async def test_list_reviews_filter_priority(
        self,
        client: AsyncClient,
        auth_headers: dict,
        multiple_reviews: list[Review],
    ):
        response = await client.get(
            "/api/reviews?priority=critical", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    async def test_list_reviews_filter_processed(
        self,
        client: AsyncClient,
        auth_headers: dict,
        multiple_reviews: list[Review],
    ):
        response = await client.get(
            "/api/reviews?is_processed=false", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    async def test_list_reviews_search(
        self,
        client: AsyncClient,
        auth_headers: dict,
        multiple_reviews: list[Review],
    ):
        response = await client.get(
            "/api/reviews?search=delivery", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    async def test_list_reviews_invalid_sentiment(
        self,
        client: AsyncClient,
        auth_headers: dict,
        email_account: EmailAccount,
    ):
        response = await client.get(
            "/api/reviews?sentiment=invalid", headers=auth_headers
        )
        assert response.status_code == 400

    async def test_list_reviews_unauthorized(self, client: AsyncClient):
        response = await client.get("/api/reviews")
        assert response.status_code == 401


class TestGetReview:
    """Tests for GET /api/reviews/{review_id}."""

    async def test_get_review_success(
        self,
        client: AsyncClient,
        auth_headers: dict,
        review: Review,
    ):
        response = await client.get(
            f"/api/reviews/{review.id}", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["subject"] == review.subject
        assert data["sentiment"] == "negative"
        assert data["priority"] == "important"
        assert "drafts" in data
        assert "email_account_email" in data

    async def test_get_review_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ):
        fake_id = uuid.uuid4()
        response = await client.get(
            f"/api/reviews/{fake_id}", headers=auth_headers
        )
        assert response.status_code == 404

    async def test_get_review_unauthorized(
        self, client: AsyncClient, review: Review
    ):
        response = await client.get(f"/api/reviews/{review.id}")
        assert response.status_code == 401


class TestUpdateReview:
    """Tests for PATCH /api/reviews/{review_id}."""

    async def test_update_review_notes(
        self,
        client: AsyncClient,
        auth_headers: dict,
        review: Review,
    ):
        response = await client.patch(
            f"/api/reviews/{review.id}",
            headers=auth_headers,
            json={"notes": "Follow up needed"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["notes"] == "Follow up needed"

    async def test_update_review_processed(
        self,
        client: AsyncClient,
        auth_headers: dict,
        review: Review,
    ):
        response = await client.patch(
            f"/api/reviews/{review.id}",
            headers=auth_headers,
            json={"is_processed": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_processed"] is False

    async def test_update_review_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ):
        fake_id = uuid.uuid4()
        response = await client.patch(
            f"/api/reviews/{fake_id}",
            headers=auth_headers,
            json={"notes": "test"},
        )
        assert response.status_code == 404


class TestGetDrafts:
    """Tests for GET /api/reviews/{review_id}/drafts."""

    async def test_get_drafts_free_plan_forbidden(
        self,
        client: AsyncClient,
        auth_headers: dict,
        review: Review,
    ):
        """FREE plan users cannot access drafts."""
        response = await client.get(
            f"/api/reviews/{review.id}/drafts", headers=auth_headers
        )
        assert response.status_code == 403

    async def test_get_drafts_pro_plan(
        self,
        client: AsyncClient,
        pro_auth_headers: dict,
        db_session,
        pro_user: User,
        review: Review,
    ):
        """PRO plan users can access drafts but need own review."""
        # Create email account for pro user
        account = EmailAccount(
            id=uuid.uuid4(),
            user_id=pro_user.id,
            email="pro@gmail.com",
            provider="gmail",
            is_active=True,
        )
        db_session.add(account)
        await db_session.flush()

        # Create review for pro user
        pro_review = Review(
            id=uuid.uuid4(),
            email_account_id=account.id,
            message_id="msg_pro_001",
            sender_email="customer@example.com",
            subject="Test review",
            received_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            is_processed=True,
        )
        db_session.add(pro_review)

        # Create draft for pro user's review
        draft = DraftResponse(
            id=uuid.uuid4(),
            review_id=pro_review.id,
            content="Draft response content",
            tone="professional",
            variant_number=1,
        )
        db_session.add(draft)
        await db_session.commit()

        response = await client.get(
            f"/api/reviews/{pro_review.id}/drafts", headers=pro_auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["drafts"]) == 1
