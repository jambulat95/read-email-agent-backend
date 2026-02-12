"""
Authentication API routes for user registration, login, and token management.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.database import get_async_session
from app.models.user import User
from app.schemas.auth import (
    RefreshTokenRequest,
    Token,
    UserCreate,
    UserResponse,
)
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Create a new user account with email and password.",
)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_async_session),
) -> User:
    """
    Register a new user.

    - **email**: Valid email address (must be unique)
    - **password**: At least 8 characters, must contain uppercase, lowercase, and digit
    - **full_name**: User's full name
    """
    auth_service = AuthService(db)

    try:
        user = await auth_service.register(user_data)
        return user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/login",
    response_model=Token,
    summary="User login",
    description="Authenticate user and return JWT tokens.",
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_async_session),
) -> Token:
    """
    Authenticate user and return JWT tokens.

    - **username**: User's email address
    - **password**: User's password

    Returns access token (30 min) and refresh token (7 days).
    """
    auth_service = AuthService(db)

    try:
        token = await auth_service.login(form_data.username, form_data.password)
        return token
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post(
    "/refresh",
    response_model=Token,
    summary="Refresh access token",
    description="Get new access and refresh tokens using a valid refresh token.",
)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_async_session),
) -> Token:
    """
    Refresh access token using a valid refresh token.

    - **refresh_token**: Valid refresh token from previous login/refresh
    """
    auth_service = AuthService(db)

    try:
        token = await auth_service.refresh_token(request.refresh_token)
        return token
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
    description="Get the currently authenticated user's information.",
)
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Get the current authenticated user's profile.

    Requires valid access token in Authorization header.
    """
    return current_user
