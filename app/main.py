"""
FastAPI application entry point.
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from app.config import get_settings

# Sentry initialization (must be before app creation)
settings_early = get_settings()
if settings_early.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration

    sentry_sdk.init(
        dsn=settings_early.sentry_dsn,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
            CeleryIntegration(),
        ],
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        environment="production" if not settings_early.debug else "development",
    )
from app.api.routes import auth as auth_routes
from app.api.routes import gmail as gmail_routes
from app.api.routes import reviews as reviews_routes
from app.api.routes import telegram as telegram_routes
from app.api.routes import analytics as analytics_routes
from app.api.routes import reports as reports_routes
from app.api.routes import billing as billing_routes
from app.api.routes import settings as settings_routes
from app.services.redis_client import close_redis_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Get settings
settings = get_settings()

# Database engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting database session."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Email Agent API...")
    logger.info(f"Debug mode: {settings.debug}")

    # Test database connection
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection established")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")

    yield

    # Cleanup
    logger.info("Shutting down Email Agent API...")
    await close_redis_client()
    await engine.dispose()


# API Tags metadata for OpenAPI documentation
tags_metadata = [
    {
        "name": "auth",
        "description": "User authentication and registration endpoints. JWT-based authentication.",
    },
    {
        "name": "gmail",
        "description": "Gmail OAuth integration for connecting email accounts.",
    },
    {
        "name": "reviews",
        "description": "Email review management - listing, details, updates, and draft responses.",
    },
    {
        "name": "analytics",
        "description": "Analytics and statistics for reviews - summary, trends, and problem breakdowns.",
    },
    {
        "name": "reports",
        "description": "Weekly reports - generation, listing, PDF download. Requires PRO or ENTERPRISE plan.",
    },
    {
        "name": "settings",
        "description": "User settings management - notifications, company info, and profile.",
    },
    {
        "name": "billing",
        "description": "Subscription billing and payment management via Stripe.",
    },
    {
        "name": "telegram",
        "description": "Telegram bot integration for notifications.",
    },
]

# Create FastAPI application
app = FastAPI(
    title="Email Agent API",
    description="""
## AI-powered Email Review and Analysis Platform

This API provides endpoints for:

- **Authentication** - User registration, login, and JWT token management
- **Gmail Integration** - Connect Gmail accounts via OAuth 2.0
- **Reviews Management** - View, filter, and manage analyzed email reviews
- **Analytics** - Get insights and statistics about your reviews
- **Reports** - Weekly analytics reports with AI recommendations and PDF export
- **Settings** - Configure notifications, company info, and user profile
- **Billing** - Subscription management and payments via Stripe
- **Telegram** - Connect Telegram for instant notifications

### Authentication

Most endpoints require a valid JWT token. Obtain one via `/api/auth/login` and include it in the `Authorization` header as `Bearer <token>`.

### Rate Limits

- Standard users: 100 requests/minute
- Enterprise API keys: 1000 requests/minute

### Subscription Plans

- **FREE**: Basic email monitoring, email notifications
- **STARTER**: + 1 draft response, Telegram notifications
- **PRO**: + 3 draft responses, SMS notifications, advanced analytics
- **ENTERPRISE**: + API access, custom integrations, priority support
    """,
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """
    Health check endpoint.

    Returns:
        dict: Status information
    """
    db_status = "unknown"

    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
            db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
        logger.error(f"Health check - DB error: {e}")

    return {
        "status": "ok",
        "database": db_status,
        "version": "0.1.0",
    }


# Include routers
app.include_router(auth_routes.router, prefix="/api")
app.include_router(gmail_routes.router, prefix="/api")
app.include_router(reviews_routes.router, prefix="/api")
app.include_router(telegram_routes.router, prefix="/api")
app.include_router(analytics_routes.router, prefix="/api")
app.include_router(reports_routes.router, prefix="/api")
app.include_router(settings_routes.router, prefix="/api")
app.include_router(billing_routes.router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Welcome to Email Agent API",
        "docs": "/docs",
        "health": "/health",
    }
