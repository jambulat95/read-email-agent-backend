"""
Gmail API client for fetching and managing emails.

Provides methods to:
- Fetch messages from Gmail
- Get message details
- Mark messages as read
- Handle authentication and token refresh
"""
import base64
import logging
import re
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_settings
from app.models.email_account import EmailAccount
from app.schemas.email import GmailMessage, MessageDetails
from app.services.encryption import get_token_encryption

logger = logging.getLogger(__name__)
settings = get_settings()


class GmailClientError(Exception):
    """Base exception for Gmail client errors."""

    pass


class GmailAuthError(GmailClientError):
    """OAuth authentication error - token invalid or revoked."""

    pass


class GmailTemporaryError(GmailClientError):
    """Temporary error - can be retried."""

    pass


class GmailRateLimitError(GmailTemporaryError):
    """Rate limit exceeded - wait before retrying."""

    pass


class GmailClient:
    """
    Gmail API client for interacting with Gmail.

    Handles OAuth tokens, message fetching, and error handling.
    """

    def __init__(self, email_account: EmailAccount):
        """
        Initialize Gmail client for a specific email account.

        Args:
            email_account: EmailAccount model with OAuth tokens
        """
        self.email_account = email_account
        self.encryption = get_token_encryption()
        self._service = None

    def _get_credentials(self) -> Credentials:
        """
        Get Google credentials from email account.

        Returns:
            Google OAuth Credentials object

        Raises:
            GmailAuthError: If tokens are missing or invalid
        """
        if not self.email_account.oauth_token:
            raise GmailAuthError("No OAuth token available")

        try:
            access_token = self.encryption.decrypt(self.email_account.oauth_token)
            refresh_token = None
            if self.email_account.oauth_refresh_token:
                refresh_token = self.encryption.decrypt(
                    self.email_account.oauth_refresh_token
                )

            credentials = Credentials(
                token=access_token,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
            )
            return credentials
        except Exception as e:
            logger.error(f"Failed to get credentials: {e}")
            raise GmailAuthError(f"Failed to decrypt OAuth tokens: {e}")

    def _get_service(self):
        """
        Get or create Gmail API service.

        Returns:
            Gmail API service object
        """
        if self._service is None:
            credentials = self._get_credentials()
            logger.info(f"Building Gmail service for {self.email_account.email}")
            try:
                self._service = build(
                    "gmail", "v1", credentials=credentials, cache_discovery=False
                )
                logger.info("Gmail service built successfully")
            except Exception as e:
                logger.error(f"Failed to build Gmail service: {e}", exc_info=True)
                raise GmailClientError(f"Failed to build Gmail service: {e}")
        return self._service

    def _handle_http_error(self, error: HttpError) -> None:
        """
        Handle Gmail API HTTP errors.

        Args:
            error: HttpError from Gmail API

        Raises:
            GmailAuthError: For auth errors (401, 403)
            GmailRateLimitError: For rate limit errors (429)
            GmailTemporaryError: For temporary errors (5xx)
            GmailClientError: For other errors
        """
        status_code = error.resp.status if error.resp else 0

        if status_code == 401:
            raise GmailAuthError("OAuth token expired or revoked")
        elif status_code == 403:
            error_reason = str(error)
            if "accessNotConfigured" in error_reason:
                raise GmailAuthError("Gmail API not enabled for this project")
            elif "insufficientPermissions" in error_reason:
                raise GmailAuthError("Insufficient OAuth permissions")
            else:
                raise GmailClientError(f"Access forbidden: {error}")
        elif status_code == 429:
            raise GmailRateLimitError("Gmail API rate limit exceeded")
        elif status_code >= 500:
            raise GmailTemporaryError(f"Gmail API server error: {error}")
        else:
            raise GmailClientError(f"Gmail API error: {error}")

    def _parse_email_address(self, from_header: str) -> tuple[str, Optional[str]]:
        """
        Parse email address from From header.

        Args:
            from_header: Email From header value

        Returns:
            Tuple of (email, name) where name may be None
        """
        name, email = parseaddr(from_header)
        return email or from_header, name or None

    def _get_header_value(self, headers: List[dict], name: str) -> str:
        """
        Get header value from list of headers.

        Args:
            headers: List of header dicts with 'name' and 'value'
            name: Header name to find (case-insensitive)

        Returns:
            Header value or empty string
        """
        name_lower = name.lower()
        for header in headers:
            if header.get("name", "").lower() == name_lower:
                return header.get("value", "")
        return ""

    def _extract_body_text(self, payload: dict) -> str:
        """
        Extract plain text body from message payload.

        Handles multipart messages and base64 encoding.

        Args:
            payload: Gmail message payload

        Returns:
            Plain text body content
        """
        body_text = ""

        # Check for direct body
        if "body" in payload and payload["body"].get("data"):
            try:
                body_text = base64.urlsafe_b64decode(
                    payload["body"]["data"]
                ).decode("utf-8", errors="replace")
            except Exception as e:
                logger.warning(f"Failed to decode body: {e}")

        # Handle multipart messages
        if "parts" in payload:
            for part in payload["parts"]:
                mime_type = part.get("mimeType", "")

                # Prefer plain text
                if mime_type == "text/plain" and part.get("body", {}).get("data"):
                    try:
                        body_text = base64.urlsafe_b64decode(
                            part["body"]["data"]
                        ).decode("utf-8", errors="replace")
                        break
                    except Exception as e:
                        logger.warning(f"Failed to decode text/plain part: {e}")

                # Recursively handle nested multipart
                if mime_type.startswith("multipart/") and "parts" in part:
                    nested_text = self._extract_body_text(part)
                    if nested_text:
                        body_text = nested_text
                        break

        return body_text.strip()

    def _extract_body_html(self, payload: dict) -> Optional[str]:
        """
        Extract HTML body from message payload.

        Args:
            payload: Gmail message payload

        Returns:
            HTML body content or None
        """
        if "parts" in payload:
            for part in payload["parts"]:
                mime_type = part.get("mimeType", "")

                if mime_type == "text/html" and part.get("body", {}).get("data"):
                    try:
                        return base64.urlsafe_b64decode(
                            part["body"]["data"]
                        ).decode("utf-8", errors="replace")
                    except Exception:
                        pass

                if mime_type.startswith("multipart/") and "parts" in part:
                    html = self._extract_body_html(part)
                    if html:
                        return html

        return None

    def _parse_date(self, date_str: str) -> datetime:
        """
        Parse email date header to datetime.

        Args:
            date_str: Date header value

        Returns:
            Parsed datetime with UTC timezone
        """
        from email.utils import parsedate_to_datetime

        try:
            dt = parsedate_to_datetime(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            # Fallback to current time
            return datetime.now(timezone.utc)

    def _build_query(self, after: Optional[datetime] = None) -> str:
        """
        Build Gmail search query.

        Args:
            after: Optional datetime to filter messages after

        Returns:
            Gmail query string
        """
        query_parts = []

        if after:
            # Gmail uses epoch seconds for after: query
            epoch = int(after.timestamp())
            query_parts.append(f"after:{epoch}")

        return " ".join(query_parts) if query_parts else ""

    def get_messages(
        self,
        after: Optional[datetime] = None,
        max_results: int = 50,
    ) -> List[GmailMessage]:
        """
        Get messages from Gmail inbox.

        Args:
            after: Only get messages after this datetime
            max_results: Maximum number of messages to return (default 50)

        Returns:
            List of GmailMessage objects

        Raises:
            GmailAuthError: If OAuth token is invalid
            GmailTemporaryError: For retryable errors
            GmailClientError: For other errors
        """
        try:
            service = self._get_service()
            query = self._build_query(after)

            logger.info(
                f"Fetching messages for {self.email_account.email}, "
                f"query: '{query}', max_results: {max_results}"
            )

            # List messages
            try:
                results = (
                    service.users()
                    .messages()
                    .list(
                        userId="me",
                        q=query,
                        maxResults=max_results,
                        labelIds=["INBOX"],
                    )
                    .execute()
                )
            except Exception as e:
                logger.error(
                    f"Gmail API messages.list failed for {self.email_account.email}: {e}",
                    exc_info=True,
                )
                raise

            messages = results.get("messages", [])
            logger.info(f"Gmail API returned {len(messages)} message IDs")
            gmail_messages = []

            for msg in messages:
                try:
                    details = self.get_message_details(msg["id"])
                    gmail_messages.append(
                        GmailMessage(
                            message_id=details.message_id,
                            thread_id=details.thread_id,
                            sender_email=details.sender_email,
                            sender_name=details.sender_name,
                            subject=details.subject,
                            body_text=details.body_text,
                            received_at=details.received_at,
                            labels=details.labels,
                        )
                    )
                except Exception as e:
                    logger.error(f"Failed to get message {msg['id']}: {e}")
                    continue

            logger.info(
                f"Fetched {len(gmail_messages)} messages for {self.email_account.email}"
            )
            return gmail_messages

        except HttpError as e:
            self._handle_http_error(e)
        except GmailClientError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching messages: {e}")
            raise GmailClientError(f"Failed to fetch messages: {e}")

    def get_message_details(self, message_id: str) -> MessageDetails:
        """
        Get detailed information about a specific message.

        Args:
            message_id: Gmail message ID

        Returns:
            MessageDetails object with full message content

        Raises:
            GmailAuthError: If OAuth token is invalid
            GmailTemporaryError: For retryable errors
            GmailClientError: For other errors
        """
        try:
            service = self._get_service()

            message = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            payload = message.get("payload", {})
            headers = payload.get("headers", [])

            # Parse headers
            from_header = self._get_header_value(headers, "From")
            sender_email, sender_name = self._parse_email_address(from_header)
            subject = self._get_header_value(headers, "Subject") or "(No Subject)"
            date_str = self._get_header_value(headers, "Date")

            # Extract body
            body_text = self._extract_body_text(payload)
            body_html = self._extract_body_html(payload)

            # Parse labels
            labels = message.get("labelIds", [])

            # Extract attachments info
            attachments = []
            if "parts" in payload:
                for part in payload["parts"]:
                    if part.get("filename"):
                        attachments.append(
                            {
                                "filename": part["filename"],
                                "mimeType": part.get("mimeType"),
                                "size": part.get("body", {}).get("size", 0),
                            }
                        )

            return MessageDetails(
                message_id=message_id,
                thread_id=message.get("threadId", ""),
                sender_email=sender_email,
                sender_name=sender_name,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                received_at=self._parse_date(date_str),
                labels=labels,
                snippet=message.get("snippet"),
                attachments=attachments,
            )

        except HttpError as e:
            self._handle_http_error(e)
        except GmailClientError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting message details: {e}")
            raise GmailClientError(f"Failed to get message details: {e}")

    def mark_as_read(self, message_id: str) -> None:
        """
        Mark a message as read by removing UNREAD label.

        Args:
            message_id: Gmail message ID

        Raises:
            GmailAuthError: If OAuth token is invalid
            GmailTemporaryError: For retryable errors
            GmailClientError: For other errors
        """
        try:
            service = self._get_service()

            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()

            logger.info(f"Marked message {message_id} as read")

        except HttpError as e:
            self._handle_http_error(e)
        except GmailClientError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error marking message as read: {e}")
            raise GmailClientError(f"Failed to mark message as read: {e}")

    def get_labels(self) -> List[dict]:
        """
        Get all labels for the Gmail account.

        Returns:
            List of label dicts with id and name

        Raises:
            GmailClientError: On API error
        """
        try:
            service = self._get_service()

            results = service.users().labels().list(userId="me").execute()
            return results.get("labels", [])

        except HttpError as e:
            self._handle_http_error(e)
        except GmailClientError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting labels: {e}")
            raise GmailClientError(f"Failed to get labels: {e}")
