"""
Token encryption service using AES-256-GCM via Fernet.

Fernet uses AES-128-CBC with HMAC for authentication. For stronger encryption
requirements, this could be upgraded to raw AES-256-GCM, but Fernet provides
a simpler, safer interface with built-in key rotation support.
"""
import base64
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class TokenEncryption:
    """
    Service for encrypting and decrypting OAuth tokens.

    Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256).
    For AES-256, we could use raw cryptography primitives, but Fernet
    provides better security guarantees for most use cases.
    """

    def __init__(self, key: Optional[str] = None):
        """
        Initialize the encryption service.

        Args:
            key: Base64-encoded Fernet key. If not provided, uses config.
        """
        settings = get_settings()
        encryption_key = key or settings.token_encryption_key

        if not encryption_key:
            raise ValueError(
                "TOKEN_ENCRYPTION_KEY is not configured. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )

        # Ensure key is bytes
        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode()

        self._fernet = Fernet(encryption_key)

    def encrypt(self, token: str) -> str:
        """
        Encrypt a token string.

        Args:
            token: Plain text token to encrypt

        Returns:
            Base64-encoded encrypted token
        """
        if not token:
            raise ValueError("Cannot encrypt empty token")

        encrypted = self._fernet.encrypt(token.encode())
        return encrypted.decode()

    def decrypt(self, encrypted: str) -> str:
        """
        Decrypt an encrypted token.

        Args:
            encrypted: Base64-encoded encrypted token

        Returns:
            Original plain text token

        Raises:
            ValueError: If decryption fails (invalid key or corrupted data)
        """
        if not encrypted:
            raise ValueError("Cannot decrypt empty string")

        try:
            decrypted = self._fernet.decrypt(encrypted.encode())
            return decrypted.decode()
        except InvalidToken as e:
            raise ValueError(f"Failed to decrypt token: invalid key or corrupted data") from e


def generate_encryption_key() -> str:
    """
    Generate a new Fernet encryption key.

    Returns:
        Base64-encoded key suitable for TOKEN_ENCRYPTION_KEY config
    """
    return Fernet.generate_key().decode()


# Singleton instance for convenience
_encryption_instance: Optional[TokenEncryption] = None


def get_token_encryption() -> TokenEncryption:
    """
    Get the singleton TokenEncryption instance.

    Returns:
        TokenEncryption instance
    """
    global _encryption_instance
    if _encryption_instance is None:
        _encryption_instance = TokenEncryption()
    return _encryption_instance
