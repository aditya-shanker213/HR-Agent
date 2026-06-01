# backend/app/database/mongo_connection.py

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings

# Single client instance — reused across all requests
_client: AsyncIOMotorClient = None
_db: AsyncIOMotorDatabase = None


async def connect_mongo() -> None:
    """
    Called at FastAPI startup.
    Creates the Motor client and connects to MongoDB.
    Motor is lazy — it doesn't actually connect until
    the first operation, so we ping to verify.
    """
    global _client, _db

    _client = AsyncIOMotorClient(settings.MONGODB_URL)
    _db = _client[settings.MONGODB_DB_NAME]

    # Ping to verify connection
    await _client.admin.command("ping")
    print(f"[startup] MongoDB connected → db: {settings.MONGODB_DB_NAME}")


async def disconnect_mongo() -> None:
    """Called at FastAPI shutdown."""
    global _client
    if _client:
        _client.close()
        print("[shutdown] MongoDB disconnected")


def get_db() -> AsyncIOMotorDatabase:
    """
    Returns the database instance.
    Called by repositories to get collection references.
    """
    if _db is None:
        raise RuntimeError("MongoDB not connected. Call connect_mongo() first.")
    return _db