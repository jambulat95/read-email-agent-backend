"""
Authentication service for user registration, login, and token management.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User
from app.schemas.auth import Token, TokenPayload, UserCreate

settings = get_settings()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.
    Uses constant-time comparison to prevent timing attacks.

    Args:
        plain_password: Plain text password to verify
        hashed_password: Hashed password to compare against

    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: UUID) -> str:
    """
    Create a JWT access token for a user.

    Args:
        user_id: The user's UUID

    Returns:
        Encoded JWT access token
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: UUID) -> str:
    """
    Create a JWT refresh token for a user.

    Args:
        user_id: The user's UUID

    Returns:
        Encoded JWT refresh token
    """
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[TokenPayload]:
    """
    Decode and validate a JWT token.

    Args:
        token: The JWT token string

    Returns:
        TokenPayload if valid, None otherwise
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return TokenPayload(
            sub=payload["sub"],
            exp=payload["exp"],
            type=payload["type"],
        )
    except JWTError:
        return None


class AuthService:
    """Service class for authentication operations."""

    def __init__(self, db: AsyncSession):
        """
        Initialize the auth service.

        Args:
            db: Database session
        """
        self.db = db

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """
        Get a user by their email address.

        Args:
            email: User's email address

        Returns:
            User if found, None otherwise
        """
        result = await self.db.execute(
            select(User).where(User.email == email.lower())
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        """
        Get a user by their ID.

        Args:
            user_id: User's UUID

        Returns:
            User if found, None otherwise
        """
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def register(self, user_data: UserCreate) -> User:
        """
        Register a new user.

        Args:
            user_data: User registration data

        Returns:
            Created user object

        Raises:
            ValueError: If email is already registered
        """
        # Check if email already exists
        existing_user = await self.get_user_by_email(user_data.email)
        if existing_user:
            raise ValueError("Email is already registered")

        # Create new user
        user = User(
            email=user_data.email.lower(),
            hashed_password=hash_password(user_data.password),
            full_name=user_data.full_name,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def login(self, email: str, password: str) -> Token:
        """
        Authenticate a user and return tokens.

        Args:
            email: User's email address
            password: User's password

        Returns:
            Token object with access and refresh tokens

        Raises:
            ValueError: If credentials are invalid
        """
        user = await self.get_user_by_email(email)

        if not user or not user.hashed_password:
            raise ValueError("Invalid email or password")

        if not verify_password(password, user.hashed_password):
            raise ValueError("Invalid email or password")

        if not user.is_active:
            raise ValueError("User account is deactivated")

        return Token(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        )

    async def refresh_token(self, refresh_token: str) -> Token:
        """
        Refresh access token using a valid refresh token.

        Args:
            refresh_token: The refresh token

        Returns:
            New Token object with fresh access and refresh tokens

        Raises:
            ValueError: If refresh token is invalid or expired
        """
        payload = decode_token(refresh_token)

        if not payload:
            raise ValueError("Invalid refresh token")

        if payload.type != "refresh":
            raise ValueError("Invalid token type")

        user = await self.get_user_by_id(UUID(payload.sub))

        if not user:
            raise ValueError("User not found")

        if not user.is_active:
            raise ValueError("User account is deactivated")

        return Token(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        )
