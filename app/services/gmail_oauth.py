"""
Gmail OAuth 2.0 service for connecting Gmail accounts.

Handles the full OAuth flow:
1. Generate authorization URL
2. Handle callback with authorization code
3. Exchange code for tokens
4. Refresh access tokens
5. Revoke access

Uses Redis for state token storage with CSRF protection.
"""
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.email_account import EmailAccount
from app.services.encryption import get_token_encryption
from app.services.redis_client import get_redis_client

logger = logging.getLogger(__name__)

settings = get_settings()

# Gmail OAuth scopes
GMAIL_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/userinfo.email",
]

# State token TTL (5 minutes)
STATE_TOKEN_TTL = 300


class GmailOAuthService:
    """Service for managing Gmail OAuth authentication."""

    def __init__(self, db: AsyncSession):
        """
        Initialize the Gmail OAuth service.

        Args:
            db: Database session
        """
        self.db = db
        self.encryption = get_token_encryption()

    def _get_client_config(self) -> dict:
        """
        Get Google OAuth client configuration.

        Returns:
            Client config dict for OAuth flow
        """
        return {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        }

    async def get_authorization_url(
        self,
        user_id: UUID,
        state: Optional[str] = None,
        redirect_to: Optional[str] = None,
    ) -> str:
        """
        Generate Gmail OAuth authorization URL.

        Creates a state token and stores it in Redis for CSRF protection.

        Args:
            user_id: ID of the user initiating the OAuth flow
            state: Optional custom state string (generated if not provided)
            redirect_to: Optional redirect destination after OAuth (e.g. "setup")

        Returns:
            Authorization URL to redirect user to
        """
        # Generate state token if not provided
        if not state:
            state = secrets.token_urlsafe(32)

        # Store state in Redis with user_id mapping
        redis = await get_redis_client()
        state_data = {
            "user_id": str(user_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if redirect_to:
            state_data["redirect_to"] = redirect_to
        await redis.setex(
            f"oauth_state:{state}",
            STATE_TOKEN_TTL,
            json.dumps(state_data),
        )

        # Create OAuth flow
        flow = Flow.from_client_config(
            self._get_client_config(),
            scopes=GMAIL_SCOPES,
            redirect_uri=settings.google_redirect_uri,
        )

        # Generate authorization URL
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )

        logger.info(f"Generated OAuth URL for user {user_id}")
        return auth_url

    async def handle_callback(self, code: str, state: str) -> tuple[EmailAccount, Optional[str]]:
        """
        Handle OAuth callback from Google.

        Validates state token, exchanges code for tokens, and creates EmailAccount.

        Args:
            code: Authorization code from Google
            state: State token for CSRF validation

        Returns:
            Tuple of (created or updated EmailAccount, optional redirect_to)

        Raises:
            ValueError: If state is invalid or expired, or OAuth fails
        """
        # Validate state token
        redis = await get_redis_client()
        state_key = f"oauth_state:{state}"
        state_data_str = await redis.get(state_key)

        if not state_data_str:
            raise ValueError("Invalid or expired state token")

        state_data = json.loads(state_data_str)
        user_id = UUID(state_data["user_id"])
        redirect_to = state_data.get("redirect_to")

        # Delete state token (one-time use)
        await redis.delete(state_key)

        # Create OAuth flow and fetch tokens
        flow = Flow.from_client_config(
            self._get_client_config(),
            scopes=GMAIL_SCOPES,
            redirect_uri=settings.google_redirect_uri,
        )

        try:
            flow.fetch_token(code=code)
        except Exception as e:
            logger.error(f"Failed to fetch OAuth tokens: {e}")
            raise ValueError(f"Failed to exchange authorization code: {str(e)}")

        credentials = flow.credentials

        # Get user email from Google
        email = await self._get_user_email(credentials)

        if not email:
            raise ValueError("Failed to retrieve email from Google")

        # Encrypt tokens
        encrypted_access_token = self.encryption.encrypt(credentials.token)
        encrypted_refresh_token = None
        if credentials.refresh_token:
            encrypted_refresh_token = self.encryption.encrypt(credentials.refresh_token)

        # Calculate token expiry
        token_expires_at = None
        if credentials.expiry:
            token_expires_at = credentials.expiry.replace(tzinfo=timezone.utc)

        # Check if account already exists
        existing_account = await self._get_account_by_email_and_user(email, user_id)

        if existing_account:
            # Update existing account
            existing_account.oauth_token = encrypted_access_token
            if encrypted_refresh_token:
                existing_account.oauth_refresh_token = encrypted_refresh_token
            existing_account.token_expires_at = token_expires_at
            existing_account.is_active = True
            await self.db.commit()
            await self.db.refresh(existing_account)
            logger.info(f"Updated existing EmailAccount for {email}")
            return existing_account, redirect_to

        # Create new account
        email_account = EmailAccount(
            user_id=user_id,
            email=email,
            provider="gmail",
            oauth_token=encrypted_access_token,
            oauth_refresh_token=encrypted_refresh_token,
            token_expires_at=token_expires_at,
            is_active=True,
        )
        self.db.add(email_account)
        await self.db.commit()
        await self.db.refresh(email_account)

        logger.info(f"Created new EmailAccount for {email}")
        return email_account, redirect_to

    async def _get_user_email(self, credentials: Credentials) -> Optional[str]:
        """
        Get user's email address from Google.

        Args:
            credentials: Google OAuth credentials

        Returns:
            User's email address or None
        """
        try:
            # Use httpx for async HTTP request to userinfo endpoint
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {credentials.token}"},
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("email")
                logger.error(f"Failed to get user info: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error getting user email: {e}")
            return None

    async def _get_account_by_email_and_user(
        self, email: str, user_id: UUID
    ) -> Optional[EmailAccount]:
        """
        Get EmailAccount by email and user ID.

        Args:
            email: Email address
            user_id: User ID

        Returns:
            EmailAccount if found, None otherwise
        """
        result = await self.db.execute(
            select(EmailAccount).where(
                EmailAccount.email == email,
                EmailAccount.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def refresh_access_token(self, email_account: EmailAccount) -> str:
        """
        Refresh the access token for an email account.

        Args:
            email_account: EmailAccount to refresh token for

        Returns:
            New access token

        Raises:
            ValueError: If refresh fails (e.g., refresh token revoked)
        """
        if not email_account.oauth_refresh_token:
            raise ValueError("No refresh token available")

        # Decrypt refresh token
        refresh_token = self.encryption.decrypt(email_account.oauth_refresh_token)

        # Create credentials object
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
        )

        try:
            # Refresh the token
            credentials.refresh(Request())
        except Exception as e:
            logger.error(f"Failed to refresh token for {email_account.email}: {e}")
            # Deactivate account on refresh failure
            email_account.is_active = False
            await self.db.commit()
            raise ValueError(f"Token refresh failed: {str(e)}. Account has been deactivated.")

        # Update account with new token
        email_account.oauth_token = self.encryption.encrypt(credentials.token)
        email_account.token_expires_at = credentials.expiry.replace(tzinfo=timezone.utc) if credentials.expiry else None
        await self.db.commit()

        logger.info(f"Refreshed access token for {email_account.email}")
        return credentials.token

    async def revoke_access(self, email_account: EmailAccount) -> None:
        """
        Revoke OAuth access for an email account.

        Revokes the token with Google and deletes the account.

        Args:
            email_account: EmailAccount to revoke access for
        """
        if email_account.oauth_token:
            try:
                # Decrypt token
                access_token = self.encryption.decrypt(email_account.oauth_token)

                # Revoke token with Google
                async with httpx.AsyncClient() as client:
                    await client.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": access_token},
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                logger.info(f"Revoked OAuth access for {email_account.email}")
            except Exception as e:
                logger.warning(f"Failed to revoke token with Google: {e}")

        # Delete the account from database
        await self.db.delete(email_account)
        await self.db.commit()

        logger.info(f"Deleted EmailAccount for {email_account.email}")

    async def get_credentials(self, email_account: EmailAccount) -> Credentials:
        """
        Get valid Google credentials for an email account.

        Automatically refreshes if token is expired.

        Args:
            email_account: EmailAccount to get credentials for

        Returns:
            Valid Google Credentials object

        Raises:
            ValueError: If credentials cannot be obtained
        """
        if not email_account.oauth_token:
            raise ValueError("No OAuth token available")

        # Decrypt tokens
        access_token = self.encryption.decrypt(email_account.oauth_token)
        refresh_token = None
        if email_account.oauth_refresh_token:
            refresh_token = self.encryption.decrypt(email_account.oauth_refresh_token)

        # Check if token is expired
        now = datetime.now(timezone.utc)
        if email_account.token_expires_at and email_account.token_expires_at <= now:
            # Token expired, refresh it
            access_token = await self.refresh_access_token(email_account)

        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
        )

        return credentials

    async def get_user_accounts(self, user_id: UUID) -> list[EmailAccount]:
        """
        Get all email accounts for a user.

        Args:
            user_id: User ID

        Returns:
            List of EmailAccount objects
        """
        result = await self.db.execute(
            select(EmailAccount).where(EmailAccount.user_id == user_id)
        )
        return list(result.scalars().all())

    async def get_account_by_id(
        self, account_id: UUID, user_id: UUID
    ) -> Optional[EmailAccount]:
        """
        Get email account by ID, ensuring it belongs to the user.

        Args:
            account_id: EmailAccount ID
            user_id: User ID

        Returns:
            EmailAccount if found and belongs to user, None otherwise
        """
        result = await self.db.execute(
            select(EmailAccount).where(
                EmailAccount.id == account_id,
                EmailAccount.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()
