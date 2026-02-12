"""
Redis client for caching and state management.

Provides async Redis operations for:
- OAuth state tokens
- Session caching
- Rate limiting
"""
import logging
from typing import Optional

import redis.asyncio as redis

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Global Redis connection pool
_redis_pool: Optional[redis.Redis] = None


async def get_redis_client() -> redis.Redis:
    """
    Get async Redis client instance.

    Uses a connection pool for efficient connection management.

    Returns:
        Async Redis client
    """
    global _redis_pool

    if _redis_pool is None:
        _redis_pool = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info("Created Redis connection pool")

    return _redis_pool


async def close_redis_client() -> None:
    """
    Close Redis connection pool.

    Should be called during application shutdown.
    """
    global _redis_pool

    if _redis_pool is not None:
        await _redis_pool.close()
        _redis_pool = None
        logger.info("Closed Redis connection pool")
