"""
Test configuration and shared fixtures.

Uses SQLite in-memory database for fast, isolated tests.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.enums import PlanType, SentimentType, PriorityType, ResponseTone
from app.models.user import User
from app.models.email_account import EmailAccount
from app.models.review import Review
from app.models.draft_response import DraftResponse
from app.models.notification_settings import NotificationSettings
from app.services.auth import create_access_token, hash_password

# SQLite async engine for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
)

TestingSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create tables and provide a test database session with rollback."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Test HTTP client with overridden database dependency."""
    from app.main import app
    from app.database import get_async_session
    from app.main import get_db

    async def override_get_async_session():
        yield db_session

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user(db_session: AsyncSession) -> User:
    """Create a test user."""
    test_user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password=hash_password("TestPass123"),
        full_name="Test User",
        is_active=True,
        is_verified=False,
        plan=PlanType.FREE,
    )
    db_session.add(test_user)
    await db_session.commit()
    await db_session.refresh(test_user)
    return test_user


@pytest_asyncio.fixture
async def pro_user(db_session: AsyncSession) -> User:
    """Create a test user with PROFESSIONAL plan."""
    test_user = User(
        id=uuid.uuid4(),
        email="pro@example.com",
        hashed_password=hash_password("TestPass123"),
        full_name="Pro User",
        is_active=True,
        is_verified=True,
        plan=PlanType.PROFESSIONAL,
    )
    db_session.add(test_user)
    await db_session.commit()
    await db_session.refresh(test_user)
    return test_user


@pytest_asyncio.fixture
async def auth_headers(user: User) -> dict:
    """JWT auth headers for the test user."""
    token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def pro_auth_headers(pro_user: User) -> dict:
    """JWT auth headers for the pro user."""
    token = create_access_token(pro_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def email_account(db_session: AsyncSession, user: User) -> EmailAccount:
    """Create a test email account."""
    account = EmailAccount(
        id=uuid.uuid4(),
        user_id=user.id,
        email="test@gmail.com",
        provider="gmail",
        is_active=True,
        check_interval_minutes=15,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


@pytest_asyncio.fixture
async def review(
    db_session: AsyncSession, email_account: EmailAccount
) -> Review:
    """Create a test review."""
    rev = Review(
        id=uuid.uuid4(),
        email_account_id=email_account.id,
        message_id="msg_001",
        sender_email="customer@example.com",
        sender_name="John Doe",
        subject="Problem with my order",
        received_at=datetime.now(timezone.utc),
        sentiment=SentimentType.NEGATIVE,
        priority=PriorityType.IMPORTANT,
        summary="Customer reports issue with order delivery",
        problems=["Delivery delay", "Wrong item"],
        suggestions=["Offer refund", "Resend correct item"],
        is_processed=True,
        processed_at=datetime.now(timezone.utc),
    )
    db_session.add(rev)
    await db_session.commit()
    await db_session.refresh(rev)
    return rev


@pytest_asyncio.fixture
async def draft_response(
    db_session: AsyncSession, review: Review
) -> DraftResponse:
    """Create a test draft response."""
    draft = DraftResponse(
        id=uuid.uuid4(),
        review_id=review.id,
        content="Dear customer, we apologize for the inconvenience...",
        tone=ResponseTone.PROFESSIONAL,
        variant_number=1,
    )
    db_session.add(draft)
    await db_session.commit()
    await db_session.refresh(draft)
    return draft


@pytest_asyncio.fixture
async def multiple_reviews(
    db_session: AsyncSession, email_account: EmailAccount
) -> list[Review]:
    """Create multiple test reviews with different sentiments and priorities."""
    reviews = []
    data = [
        (SentimentType.POSITIVE, PriorityType.NORMAL, "Great service!", True),
        (SentimentType.NEGATIVE, PriorityType.CRITICAL, "Terrible experience", True),
        (SentimentType.NEUTRAL, PriorityType.NORMAL, "Question about order", False),
        (SentimentType.NEGATIVE, PriorityType.IMPORTANT, "Late delivery", True),
        (SentimentType.POSITIVE, PriorityType.NORMAL, "Love the product", True),
    ]
    for i, (sentiment, priority, subject, processed) in enumerate(data):
        rev = Review(
            id=uuid.uuid4(),
            email_account_id=email_account.id,
            message_id=f"msg_{i+100}",
            sender_email=f"customer{i}@example.com",
            sender_name=f"Customer {i}",
            subject=subject,
            received_at=datetime.now(timezone.utc),
            sentiment=sentiment,
            priority=priority,
            summary=f"Summary for {subject}",
            problems=["Issue"] if sentiment == SentimentType.NEGATIVE else [],
            is_processed=processed,
            processed_at=datetime.now(timezone.utc) if processed else None,
        )
        db_session.add(rev)
        reviews.append(rev)

    await db_session.commit()
    for rev in reviews:
        await db_session.refresh(rev)
    return reviews
