"""Tests for notification service."""
import uuid
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.models.enums import PlanType, PriorityType
from app.models.notification_settings import NotificationSettings
from app.models.review import Review
from app.models.user import User
from app.services.notification_service import (
    NotificationService,
    NotificationSummary,
    PLAN_CHANNELS,
)
from app.services.notifications.base import (
    Notification,
    NotificationResult,
)


@pytest.fixture
def mock_channels():
    """Create mock notification channels."""
    email = MagicMock()
    email.channel_name = "email"
    email.is_configured.return_value = True
    email.send = AsyncMock(
        return_value=NotificationResult(success=True, channel="email")
    )

    telegram = MagicMock()
    telegram.channel_name = "telegram"
    telegram.is_configured.return_value = True
    telegram.send = AsyncMock(
        return_value=NotificationResult(success=True, channel="telegram")
    )

    sms = MagicMock()
    sms.channel_name = "sms"
    sms.is_configured.return_value = True
    sms.send = AsyncMock(
        return_value=NotificationResult(success=True, channel="sms")
    )

    return email, telegram, sms


@pytest.fixture
def notification_service(mock_channels):
    """Create a notification service with mock channels."""
    email, telegram, sms = mock_channels

    with patch("app.services.notification_service.get_email_channel", return_value=email), \
         patch("app.services.notification_service.get_telegram_channel", return_value=telegram), \
         patch("app.services.notification_service.get_sms_channel", return_value=sms):
        service = NotificationService()

    return service


@pytest.fixture
def free_user():
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "free@example.com"
    user.plan = PlanType.FREE
    user.notification_settings = None
    return user


@pytest.fixture
def pro_user():
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "pro@example.com"
    user.plan = PlanType.PROFESSIONAL

    settings = MagicMock(spec=NotificationSettings)
    settings.email_enabled = True
    settings.telegram_enabled = True
    settings.telegram_chat_id = "123456"
    settings.sms_enabled = True
    settings.phone_number = "+1234567890"
    settings.notify_on_critical = True
    settings.notify_on_important = True
    settings.notify_on_normal = False
    user.notification_settings = settings
    return user


@pytest.fixture
def test_review():
    review = MagicMock(spec=Review)
    review.id = uuid.uuid4()
    review.message_id = "msg_001"
    review.sender_email = "customer@example.com"
    review.sender_name = "Customer"
    review.subject = "Issue with order"
    review.summary = "Customer reports delayed delivery"
    review.priority = PriorityType.CRITICAL
    review.problems = ["Delivery delay"]
    return review


class TestPlanChannels:
    def test_free_plan_email_only(self):
        assert PLAN_CHANNELS[PlanType.FREE] == ["email"]

    def test_starter_plan(self):
        channels = PLAN_CHANNELS[PlanType.STARTER]
        assert "email" in channels
        assert "telegram" in channels
        assert "sms" not in channels

    def test_pro_plan_all_channels(self):
        channels = PLAN_CHANNELS[PlanType.PROFESSIONAL]
        assert "email" in channels
        assert "telegram" in channels
        assert "sms" in channels


class TestGetAvailableChannels:
    def test_free_user(self, notification_service, free_user):
        channels = notification_service.get_available_channels(free_user)
        assert channels == ["email"]

    def test_pro_user(self, notification_service, pro_user):
        channels = notification_service.get_available_channels(pro_user)
        assert "email" in channels
        assert "telegram" in channels
        assert "sms" in channels


class TestShouldNotify:
    def test_critical_default(self, notification_service):
        """Default: notify on critical."""
        assert notification_service.should_notify(PriorityType.CRITICAL, None) is True

    def test_important_default(self, notification_service):
        """Default: notify on important."""
        assert notification_service.should_notify(PriorityType.IMPORTANT, None) is True

    def test_normal_default(self, notification_service):
        """Default: don't notify on normal."""
        assert notification_service.should_notify(PriorityType.NORMAL, None) is False

    def test_with_settings_critical(self, notification_service, pro_user):
        assert notification_service.should_notify(
            PriorityType.CRITICAL, pro_user.notification_settings
        ) is True

    def test_with_settings_normal_disabled(self, notification_service, pro_user):
        assert notification_service.should_notify(
            PriorityType.NORMAL, pro_user.notification_settings
        ) is False


class TestBuildNotification:
    def test_build_notification(self, notification_service, test_review):
        notification = notification_service.build_notification(test_review)
        assert notification.review_id == test_review.id
        assert notification.priority == "critical"
        assert notification.summary == test_review.summary
        assert notification.sender_email == test_review.sender_email
        assert "dashboard" in notification.dashboard_url.lower() or "reviews" in notification.dashboard_url


class TestSendReviewNotification:
    async def test_skip_normal_priority(
        self, notification_service, free_user, test_review
    ):
        """Normal priority skips notification by default."""
        test_review.priority = PriorityType.NORMAL
        summary = await notification_service.send_review_notification(
            test_review, free_user
        )
        assert summary.total_channels == 0

    async def test_send_critical_free_user(
        self, notification_service, free_user, test_review, mock_channels
    ):
        """Free user gets email notification for critical reviews."""
        email_channel, _, _ = mock_channels
        notification_service._email = email_channel

        summary = await notification_service.send_review_notification(
            test_review, free_user
        )
        assert summary.total_channels == 1
        assert summary.successful == 1


class TestNotificationSummary:
    def test_all_successful(self):
        summary = NotificationSummary(
            review_id="test",
            total_channels=2,
            successful=2,
            failed=0,
            results=[
                NotificationResult(success=True, channel="email"),
                NotificationResult(success=True, channel="telegram"),
            ],
        )
        assert summary.all_successful is True
        assert summary.any_successful is True

    def test_partial_failure(self):
        summary = NotificationSummary(
            review_id="test",
            total_channels=2,
            successful=1,
            failed=1,
            results=[
                NotificationResult(success=True, channel="email"),
                NotificationResult(success=False, channel="telegram", error="API error"),
            ],
        )
        assert summary.all_successful is False
        assert summary.any_successful is True

    def test_no_channels(self):
        summary = NotificationSummary(
            review_id="test",
            total_channels=0,
            successful=0,
            failed=0,
            results=[],
        )
        assert summary.all_successful is False
        assert summary.any_successful is False
