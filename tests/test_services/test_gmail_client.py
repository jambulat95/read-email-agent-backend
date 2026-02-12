"""Tests for Gmail client service."""
import base64
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.email_account import EmailAccount
from app.services.gmail_client import (
    GmailAuthError,
    GmailClient,
    GmailClientError,
    GmailRateLimitError,
    GmailTemporaryError,
)


@pytest.fixture
def email_account_obj():
    """Create a mock email account."""
    account = MagicMock(spec=EmailAccount)
    account.id = uuid.uuid4()
    account.email = "test@gmail.com"
    account.oauth_token = "encrypted_token"
    account.oauth_refresh_token = "encrypted_refresh"
    return account


@pytest.fixture
def gmail_client(email_account_obj):
    """Create a Gmail client with mocked encryption."""
    with patch("app.services.gmail_client.get_token_encryption") as mock_enc:
        mock_enc.return_value.decrypt.return_value = "decrypted_token"
        client = GmailClient(email_account_obj)
    return client


class TestGmailClientInit:
    def test_missing_oauth_token(self):
        account = MagicMock(spec=EmailAccount)
        account.oauth_token = None

        with patch("app.services.gmail_client.get_token_encryption"):
            client = GmailClient(account)

        with pytest.raises(GmailAuthError, match="No OAuth token"):
            client._get_credentials()


class TestParseEmailAddress:
    def test_parse_name_and_email(self, gmail_client):
        email, name = gmail_client._parse_email_address(
            "John Doe <john@example.com>"
        )
        assert email == "john@example.com"
        assert name == "John Doe"

    def test_parse_email_only(self, gmail_client):
        email, name = gmail_client._parse_email_address("john@example.com")
        assert email == "john@example.com"
        assert name is None

    def test_parse_empty_string(self, gmail_client):
        email, name = gmail_client._parse_email_address("")
        assert name is None


class TestGetHeaderValue:
    def test_get_existing_header(self, gmail_client):
        headers = [
            {"name": "From", "value": "test@example.com"},
            {"name": "Subject", "value": "Test Subject"},
        ]
        assert gmail_client._get_header_value(headers, "Subject") == "Test Subject"

    def test_get_missing_header(self, gmail_client):
        headers = [{"name": "From", "value": "test@example.com"}]
        assert gmail_client._get_header_value(headers, "Subject") == ""

    def test_case_insensitive(self, gmail_client):
        headers = [{"name": "Content-Type", "value": "text/plain"}]
        assert gmail_client._get_header_value(headers, "content-type") == "text/plain"


class TestExtractBodyText:
    def test_direct_body(self, gmail_client):
        encoded = base64.urlsafe_b64encode(b"Hello World").decode()
        payload = {"body": {"data": encoded}}
        assert gmail_client._extract_body_text(payload) == "Hello World"

    def test_multipart_text(self, gmail_client):
        encoded = base64.urlsafe_b64encode(b"Plain text body").decode()
        payload = {
            "body": {},
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": encoded},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": base64.urlsafe_b64encode(b"<b>HTML</b>").decode()},
                },
            ],
        }
        assert gmail_client._extract_body_text(payload) == "Plain text body"

    def test_empty_payload(self, gmail_client):
        payload = {"body": {}}
        assert gmail_client._extract_body_text(payload) == ""


class TestBuildQuery:
    def test_no_after(self, gmail_client):
        assert gmail_client._build_query() == ""

    def test_with_after(self, gmail_client):
        after = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        query = gmail_client._build_query(after)
        assert query.startswith("after:")
        assert str(int(after.timestamp())) in query


class TestHandleHttpError:
    def test_401_raises_auth_error(self, gmail_client):
        error = MagicMock()
        error.resp.status = 401
        with pytest.raises(GmailAuthError):
            gmail_client._handle_http_error(error)

    def test_429_raises_rate_limit(self, gmail_client):
        error = MagicMock()
        error.resp.status = 429
        with pytest.raises(GmailRateLimitError):
            gmail_client._handle_http_error(error)

    def test_500_raises_temporary_error(self, gmail_client):
        error = MagicMock()
        error.resp.status = 500
        with pytest.raises(GmailTemporaryError):
            gmail_client._handle_http_error(error)

    def test_403_raises_client_error(self, gmail_client):
        error = MagicMock()
        error.resp.status = 403
        error.__str__ = lambda self: "forbidden"
        with pytest.raises(GmailClientError):
            gmail_client._handle_http_error(error)


class TestParseDate:
    def test_valid_date(self, gmail_client):
        dt = gmail_client._parse_date("Mon, 01 Jan 2024 12:00:00 +0000")
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.tzinfo is not None

    def test_invalid_date_fallback(self, gmail_client):
        dt = gmail_client._parse_date("not a date")
        assert dt.tzinfo is not None
        # Should return current time as fallback
