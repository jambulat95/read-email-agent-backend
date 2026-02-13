"""
Gmail OAuth API routes for connecting and managing Gmail accounts.

Endpoints:
- GET /api/gmail/connect - Get OAuth authorization URL
- GET /api/gmail/callback - Handle OAuth callback from Google
- GET /api/gmail/accounts - List connected email accounts
- DELETE /api/gmail/accounts/{id} - Disconnect/revoke email account
- PATCH /api/gmail/accounts/{id} - Update account settings
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.config import get_settings
from app.database import get_async_session
from app.models.user import User
from app.schemas.gmail import (
    EmailAccountListResponse,
    EmailAccountResponse,
    EmailAccountUpdate,
    OAuthCallbackResponse,
    OAuthConnectResponse,
)
from app.services.gmail_oauth import GmailOAuthService

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/gmail", tags=["Gmail"])


@router.get(
    "/connect",
    response_model=OAuthConnectResponse,
    summary="Get Gmail OAuth URL",
    description="Generate authorization URL for connecting a Gmail account.",
)
async def connect_gmail(
    redirect_to: str = Query(None, description="Redirect destination after OAuth (e.g. 'setup')"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> OAuthConnectResponse:
    """
    Get authorization URL for Gmail OAuth.

    Returns a URL that the frontend should redirect the user to
    for Google authentication.
    """
    # Check if Google OAuth is configured
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        )

    oauth_service = GmailOAuthService(db)
    auth_url = await oauth_service.get_authorization_url(
        current_user.id, redirect_to=redirect_to
    )

    return OAuthConnectResponse(
        authorization_url=auth_url,
        message="Redirect user to authorization_url to connect Gmail",
    )


@router.get(
    "/callback",
    response_class=RedirectResponse,
    summary="OAuth callback",
    description="Handle OAuth callback from Google after user authorization.",
)
async def oauth_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="State token for CSRF protection"),
    error: str = Query(None, description="Error from Google OAuth"),
    db: AsyncSession = Depends(get_async_session),
) -> RedirectResponse:
    """
    Handle OAuth callback from Google.

    This endpoint is called by Google after user grants permission.
    It exchanges the authorization code for tokens and creates the EmailAccount.
    Then redirects to frontend with success/error status.
    """
    frontend_url = settings.frontend_url

    # Handle Google OAuth errors
    if error:
        logger.error(f"OAuth error from Google: {error}")
        return RedirectResponse(
            url=f"{frontend_url}/dashboard/settings/accounts?error=oauth_denied&message={error}"
        )

    try:
        oauth_service = GmailOAuthService(db)
        email_account, redirect_to = await oauth_service.handle_callback(code, state)

        logger.info(f"Successfully connected Gmail account: {email_account.email}")

        # Redirect based on redirect_to from OAuth state
        if redirect_to == "setup":
            return RedirectResponse(
                url=f"{frontend_url}/setup?step=2&gmail=connected"
            )

        # Default: redirect to settings page
        return RedirectResponse(
            url=f"{frontend_url}/dashboard/settings/accounts?success=true&email={email_account.email}"
        )

    except ValueError as e:
        logger.error(f"OAuth callback error: {e}")
        return RedirectResponse(
            url=f"{frontend_url}/dashboard/settings/accounts?error=oauth_failed&message={str(e)}"
        )
    except Exception as e:
        logger.exception(f"Unexpected OAuth callback error: {e}")
        return RedirectResponse(
            url=f"{frontend_url}/dashboard/settings/accounts?error=internal_error"
        )


@router.get(
    "/accounts",
    response_model=EmailAccountListResponse,
    summary="List email accounts",
    description="Get all connected email accounts for the current user.",
)
async def list_accounts(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> EmailAccountListResponse:
    """
    List all connected email accounts.

    Returns all Gmail accounts connected by the current user.
    """
    oauth_service = GmailOAuthService(db)
    accounts = await oauth_service.get_user_accounts(current_user.id)

    return EmailAccountListResponse(
        accounts=[EmailAccountResponse.model_validate(acc) for acc in accounts],
        total=len(accounts),
    )


@router.delete(
    "/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect email account",
    description="Revoke access and remove an email account.",
)
async def disconnect_account(
    account_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> None:
    """
    Disconnect and revoke access for an email account.

    Revokes the OAuth token with Google and removes the account.
    """
    oauth_service = GmailOAuthService(db)
    account = await oauth_service.get_account_by_id(account_id, current_user.id)

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email account not found",
        )

    await oauth_service.revoke_access(account)
    logger.info(f"Disconnected email account: {account.email} for user {current_user.id}")


@router.patch(
    "/accounts/{account_id}",
    response_model=EmailAccountResponse,
    summary="Update account settings",
    description="Update settings for an email account (e.g., check interval).",
)
async def update_account(
    account_id: UUID,
    update_data: EmailAccountUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> EmailAccountResponse:
    """
    Update email account settings.

    Currently supports updating:
    - check_interval_minutes: How often to check for new emails (5-1440 minutes)
    """
    oauth_service = GmailOAuthService(db)
    account = await oauth_service.get_account_by_id(account_id, current_user.id)

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email account not found",
        )

    # Update fields if provided
    if update_data.check_interval_minutes is not None:
        account.check_interval_minutes = update_data.check_interval_minutes

    await db.commit()
    await db.refresh(account)

    logger.info(f"Updated email account settings: {account.email}")
    return EmailAccountResponse.model_validate(account)
