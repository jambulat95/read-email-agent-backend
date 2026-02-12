"""
Application configuration using pydantic-settings.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/email_agent"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Security
    secret_key: str = "your-secret-key-change-in-production"

    # Application
    debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:8000"

    # JWT Configuration
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Google OAuth Configuration
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/gmail/callback"

    # Token Encryption (AES-256 key, 32 bytes base64 encoded)
    token_encryption_key: str = ""

    # Frontend URL for OAuth callback redirect
    frontend_url: str = "http://localhost:3000"

    # AI / Mistral Configuration
    mistral_api_key: str = ""
    ai_model: str = "mistral-large-latest"
    ai_max_tokens: int = 1000
    ai_temperature: float = 0.3

    # Notifications - SendGrid (Email)
    sendgrid_api_key: str = ""
    notification_from_email: str = "noreply@emailagent.com"

    # Notifications - Telegram
    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""

    # Notifications - Twilio (SMS)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Dashboard URL for notification links
    dashboard_url: str = "http://localhost:3000"

    # Monitoring
    sentry_dsn: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter_monthly: str = ""
    stripe_price_starter_yearly: str = ""
    stripe_price_pro_monthly: str = ""
    stripe_price_pro_yearly: str = ""
    stripe_price_enterprise_monthly: str = ""

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.cors_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
