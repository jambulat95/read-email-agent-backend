"""
API dependencies for authentication and authorization.
"""
from typing import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models.enums import PlanType
from app.models.user import User
from app.services.auth import AuthService, decode_token

# OAuth2 scheme for token extraction from Authorization header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Plan hierarchy for comparison
PLAN_HIERARCHY = {
    PlanType.FREE: 0,
    PlanType.STARTER: 1,
    PlanType.PROFESSIONAL: 2,
    PlanType.ENTERPRISE: 3,
}


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_async_session),
) -> User:
    """
    Get the current authenticated user from the JWT token.

    Args:
        token: JWT access token from Authorization header
        db: Database session

    Returns:
        Current authenticated user

    Raises:
        HTTPException: If token is invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if not payload:
        raise credentials_exception

    if payload.type != "access":
        raise credentials_exception

    auth_service = AuthService(db)
    user = await auth_service.get_user_by_id(UUID(payload.sub))

    if not user:
        raise credentials_exception

    return user


async def get_current_active_user(
    user: User = Depends(get_current_user),
) -> User:
    """
    Get the current active user.

    Args:
        user: Current authenticated user

    Returns:
        Current active user

    Raises:
        HTTPException: If user is not active
    """
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )
    return user


def require_plan(min_plan: PlanType) -> Callable:
    """
    Create a dependency that checks if user has at least the specified plan.

    Args:
        min_plan: Minimum required plan level

    Returns:
        Dependency function that validates the user's plan

    Usage:
        @router.get("/premium-feature")
        async def premium_feature(
            user: User = Depends(require_plan(PlanType.PROFESSIONAL))
        ):
            ...
    """

    async def plan_checker(
        user: User = Depends(get_current_active_user),
    ) -> User:
        """Check if user has required plan level."""
        user_plan_level = PLAN_HIERARCHY.get(PlanType(user.plan), 0)
        required_plan_level = PLAN_HIERARCHY.get(min_plan, 0)

        if user_plan_level < required_plan_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This feature requires {min_plan.value} plan or higher",
            )
        return user

    return plan_checker
