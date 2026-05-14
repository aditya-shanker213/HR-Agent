"""
Redis connection configuration.

Creates a single Redis connection pool shared across the application.

Used for:
- OTP storage with automatic expiry
- Session/conversation memory for LangGraph
- Rate limiting counters
- Temporary cache

Pattern:
- Connect once at FastAPI startup
- Reuse one connection pool across requests
- Close connection at FastAPI shutdown
"""

from typing import Optional

import redis.asyncio as redis

from backend.app.core.config import settings


class RedisDB:
    """
    Redis connection manager.

    One connection pool is shared for the full application lifecycle.
    """

    pool: Optional[redis.ConnectionPool] = None
    client: Optional[redis.Redis] = None

    @classmethod
    async def connect(cls) -> None:
        """
        Connect to Redis.

        Called once during application startup.
        """
        if cls.pool is not None and cls.client is not None:
            return

        cls.pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=settings.REDIS_DECODE_RESPONSES,
            encoding="utf-8",
        )

        cls.client = redis.Redis(connection_pool=cls.pool)

        try:
            await cls.client.ping()
            print("Connected to Redis")
        except Exception as exc:
            if cls.client is not None:
                await cls.client.aclose()

            if cls.pool is not None:
                await cls.pool.aclose()

            cls.client = None
            cls.pool = None

            raise RuntimeError(f"Failed to connect to Redis: {exc}") from exc

    @classmethod
    async def disconnect(cls) -> None:
        """
        Close Redis connection.

        Called once during application shutdown.
        """
        if cls.client is not None:
            await cls.client.aclose()

        if cls.pool is not None:
            await cls.pool.aclose()

        cls.client = None
        cls.pool = None

        print("Disconnected from Redis")

    @classmethod
    def get_client(cls) -> redis.Redis:
        """
        Get Redis client instance.

        Raises RuntimeError if Redis is not connected.
        """
        if cls.client is None:
            raise RuntimeError(
                "Redis is not connected. "
                "Call RedisDB.connect() during application startup."
            )

        return cls.client


def get_redis() -> redis.Redis:
    """
    Get Redis client.

    Use this in services or dependencies when needed.
    """
    return RedisDB.get_client()


def get_redis_client() -> redis.Redis:
    """
    Clear alias for get_redis().
    """
    return RedisDB.get_client()


async def get_redis_dependency() -> redis.Redis:
    """
    FastAPI dependency for injecting Redis client.
    """
    return RedisDB.get_client()


async def redis_health_check() -> bool:
    """
    Check whether Redis is healthy.
    """
    try:
        client = RedisDB.get_client()
        response = await client.ping()
        return response is True
    except Exception:
        return False


async def clear_redis_pattern(pattern: str) -> int:
    """
    Delete all keys matching a pattern.

    Examples:
    - clear_redis_pattern("otp:*")
    - clear_redis_pattern("otp_rate_limit:*")
    - clear_redis_pattern("session:*")

    Be careful using this in production.
    """
    client = RedisDB.get_client()

    cursor = 0
    deleted_count = 0

    while True:
        cursor, keys = await client.scan(
            cursor=cursor,
            match=pattern,
            count=100,
        )

        if keys:
            deleted = await client.delete(*keys)
            deleted_count += int(deleted)

        if cursor == 0:
            break

    return deleted_count


async def get_redis_info() -> dict:
    """
    Get basic Redis server information.

    Useful for health dashboard or debugging.
    """
    client = RedisDB.get_client()
    info = await client.info()

    return {
        "version": info.get("redis_version"),
        "connected_clients": info.get("connected_clients"),
        "used_memory_human": info.get("used_memory_human"),
        "uptime_in_days": info.get("uptime_in_days"),
        "total_commands_processed": info.get("total_commands_processed"),
    }