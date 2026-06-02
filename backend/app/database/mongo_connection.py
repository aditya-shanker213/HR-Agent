"""
MongoDB connection configuration.

Creates a single Motor AsyncIOMotorClient shared across the application.

Pattern:
- Connect once at FastAPI startup
- Reuse one connection pool across all requests
- Close connection at FastAPI shutdown
- Repositories receive the database object and perform MongoDB queries
"""

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from backend.app.core.config import settings


class MongoDB:
    """
    MongoDB connection manager.

    One client is shared for the full application lifecycle.
    """

    client: Optional[AsyncIOMotorClient] = None
    database: Optional[AsyncIOMotorDatabase] = None

    @classmethod
    async def connect(cls) -> None:
        """
        Connect to MongoDB.

        Called once during application startup.
        """
        if cls.client is not None and cls.database is not None:
            return

        cls.client = AsyncIOMotorClient(
            settings.MONGO_URI,
            maxPoolSize=settings.MONGO_MAX_POOL_SIZE,
            minPoolSize=settings.MONGO_MIN_POOL_SIZE,
            serverSelectionTimeoutMS=5000,
        )

        cls.database = cls.client[settings.MONGO_DB_NAME]

        try:
            await cls.client.admin.command("ping")
            print(f"Connected to MongoDB database: {settings.MONGO_DB_NAME}")
        except Exception as exc:
            cls.client.close()
            cls.client = None
            cls.database = None
            raise RuntimeError(f"Failed to connect to MongoDB: {exc}") from exc

    @classmethod
    async def disconnect(cls) -> None:
        """
        Close MongoDB connection.

        Called once during application shutdown.
        """
        if cls.client is not None:
            cls.client.close()

        cls.client = None
        cls.database = None
        print("Disconnected from MongoDB")

    @classmethod
    def get_database(cls) -> AsyncIOMotorDatabase:
        """
        Return MongoDB database instance.

        Raises RuntimeError if MongoDB is not connected.
        """
        if cls.database is None:
            raise RuntimeError(
                "MongoDB is not connected. "
                "Call MongoDB.connect() during application startup."
            )

        return cls.database

    @classmethod
    def get_client(cls) -> AsyncIOMotorClient:
        """
        Return MongoDB client instance.

        Useful for transactions or admin-level operations.
        """
        if cls.client is None:
            raise RuntimeError(
                "MongoDB is not connected. "
                "Call MongoDB.connect() during application startup."
            )

        return cls.client


# -------------------------
# Collection accessors
# -------------------------

def get_users_collection():
    return MongoDB.get_database().users


def get_employees_collection():
    return MongoDB.get_database().employees


def get_leaves_collection():
    return MongoDB.get_database().leaves


def get_claims_collection():
    return MongoDB.get_database().claims


def get_payroll_collection():
    return MongoDB.get_database().payroll


def get_tickets_collection():
    return MongoDB.get_database().tickets


def get_audit_logs_collection():
    return MongoDB.get_database().audit_logs


def get_tool_logs_collection():
    return MongoDB.get_database().tool_logs


def get_policies_collection():
    return MongoDB.get_database().policies


def get_chat_logs_collection():
    return MongoDB.get_database().chat_logs


class DatabaseCollections:
    """
    Convenience wrapper for collection access.

    Use carefully. Repositories are still preferred for database queries.
    """

    @property
    def users(self):
        return get_users_collection()

    @property
    def employees(self):
        return get_employees_collection()

    @property
    def leaves(self):
        return get_leaves_collection()

    @property
    def claims(self):
        return get_claims_collection()

    @property
    def payroll(self):
        return get_payroll_collection()

    @property
    def tickets(self):
        return get_tickets_collection()

    @property
    def audit_logs(self):
        return get_audit_logs_collection()

    @property
    def tool_logs(self):
        return get_tool_logs_collection()

    @property
    def policies(self):
        return get_policies_collection()

    @property
    def chat_logs(self):
        return get_chat_logs_collection()


db = DatabaseCollections()


async def get_database() -> AsyncIOMotorDatabase:
    """
    FastAPI dependency for injecting database.

    Example:
        db = Depends(get_database)
    """
    return MongoDB.get_database()