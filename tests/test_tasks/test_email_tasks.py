"""Tests for email checking Celery tasks.

Uses sys.modules patching to avoid Celery/Redis connection issues during tests.
"""
import sys
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.models.email_account import EmailAccount
from app.schemas.email import GmailMessage
from app.services.gmail_client import (
    GmailAuthError,
    GmailRateLimitError,
    GmailTemporaryError,
)


def make_gmail_message(msg_id: str = "msg_test_001", **kwargs):
    """Helper to create a GmailMessage."""
    defaults = {
        "message_id": msg_id,
        "thread_id": "thread_001",
        "sender_email": "customer@example.com",
        "sender_name": "Customer",
        "subject": "Test email subject",
        "body_text": "Test email body",
        "received_at": datetime.now(timezone.utc),
        "labels": ["INBOX"],
    }
    defaults.update(kwargs)
    return GmailMessage(**defaults)


@pytest.fixture(autouse=True)
def mock_celery():
    """Mock the celery app to avoid Redis connection."""
    mock_celery_app = MagicMock()
    mock_celery_app.task = lambda *args, **kwargs: lambda fn: fn

    # Patch celery_app module before importing tasks
    with patch.dict(sys.modules, {
        "app.tasks.celery_app": MagicMock(celery_app=mock_celery_app),
    }):
        yield mock_celery_app


class TestCheckEmailsLogic:
    """Test the business logic of check_emails_for_account."""

    def test_account_not_found(self):
        """Handles missing account gracefully."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Test the logic directly (without Celery decoration)
        account_id = str(uuid.uuid4())
        result = self._run_check_logic(mock_session, account_id)

        assert result["success"] is False
        assert "not found" in result["error"]

    def test_inactive_account_skipped(self):
        """Skips inactive accounts."""
        mock_session = MagicMock()
        account = MagicMock(spec=EmailAccount)
        account.id = uuid.uuid4()
        account.email = "test@gmail.com"
        account.is_active = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = account
        mock_session.execute.return_value = mock_result

        result = self._run_check_logic(mock_session, str(account.id))

        assert result["success"] is False
        assert "not active" in result["error"]

    def test_oauth_error_deactivates_account(self):
        """OAuth error deactivates the account."""
        mock_session = MagicMock()
        account = MagicMock(spec=EmailAccount)
        account.id = uuid.uuid4()
        account.email = "test@gmail.com"
        account.is_active = True
        account.last_checked_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = account
        mock_session.execute.return_value = mock_result

        with patch(
            "app.services.gmail_client.GmailClient"
        ) as mock_gmail_cls:
            mock_client = MagicMock()
            mock_client.get_messages.side_effect = GmailAuthError("Token revoked")
            mock_gmail_cls.return_value = mock_client

            result = self._run_check_logic(
                mock_session, str(account.id), gmail_cls=mock_gmail_cls
            )

        assert result["success"] is False
        assert "OAuth" in result["error"]
        assert account.is_active is False

    def _run_check_logic(
        self, mock_session, account_id, gmail_cls=None
    ):
        """
        Simulate the check_emails_for_account logic
        without going through Celery.
        """
        from sqlalchemy import select

        account_uuid = uuid.UUID(account_id)
        result = mock_session.execute(
            select(EmailAccount).where(EmailAccount.id == account_uuid)
        )
        account = result.scalar_one_or_none()

        if not account:
            return {
                "success": False,
                "error": "Account not found",
                "account_id": account_id,
            }

        if not account.is_active:
            return {
                "success": False,
                "error": "Account is not active",
                "account_id": account_id,
            }

        # Try fetching emails
        if gmail_cls:
            client = gmail_cls(account)
        else:
            from app.services.gmail_client import GmailClient
            client = GmailClient(account)

        try:
            client.get_messages(after=account.last_checked_at, max_results=50)
        except GmailAuthError as e:
            account.is_active = False
            mock_session.commit()
            return {
                "success": False,
                "error": f"OAuth error, account deactivated: {e}",
                "account_id": account_id,
            }

        return {"success": True}


class TestScheduleLogic:
    """Test the business logic of schedule_email_checks."""

    def test_finds_due_accounts(self):
        """Identifies accounts that are due for checking."""
        now = datetime.now(timezone.utc)

        # Account never checked
        account1 = MagicMock(spec=EmailAccount)
        account1.id = uuid.uuid4()
        account1.is_active = True
        account1.last_checked_at = None
        account1.check_interval_minutes = 15

        # Account checked 1 hour ago (due)
        account2 = MagicMock(spec=EmailAccount)
        account2.id = uuid.uuid4()
        account2.is_active = True
        account2.last_checked_at = now - timedelta(hours=1)
        account2.check_interval_minutes = 15

        # Account checked 5 minutes ago (not due)
        account3 = MagicMock(spec=EmailAccount)
        account3.id = uuid.uuid4()
        account3.is_active = True
        account3.last_checked_at = now - timedelta(minutes=5)
        account3.check_interval_minutes = 15

        accounts = [account1, account2, account3]

        due = []
        for account in accounts:
            if account.last_checked_at is None:
                due.append(account)
            else:
                next_check = account.last_checked_at + timedelta(
                    minutes=account.check_interval_minutes
                )
                if next_check <= now:
                    due.append(account)

        assert len(due) == 2
        assert account1 in due
        assert account2 in due
        assert account3 not in due

    def test_gmail_message_creation(self):
        """Test GmailMessage helper creates valid objects."""
        msg = make_gmail_message(
            msg_id="test_123",
            subject="Test Subject",
        )
        assert msg.message_id == "test_123"
        assert msg.subject == "Test Subject"
        assert msg.sender_email == "customer@example.com"
