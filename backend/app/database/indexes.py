"""
MongoDB index creation for project collections.

Indexes are created at application startup to ensure:
- Unique usernames and emails
- Fast login/admin queries
- Unique department codes
- Fast department listing, filtering, searching, and hierarchy lookups

Pattern:
FastAPI startup -> MongoDB connect -> create_indexes(db)

Important:
Index creation is idempotent.
It is safe to run multiple times because MongoDB will not recreate the same
index again if it already exists.
"""

from typing import Any, Dict, List

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, TEXT


class IndexManager:
    """
    Manages MongoDB index creation.

    Keep all collection indexes here so staging, production, and local
    development use the same database structure.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def create_all_indexes(self) -> Dict[str, Any]:
        """
        Create all required indexes.

        Returns:
            Dictionary with index creation results.
        """
        results: Dict[str, Any] = {}

        print("Creating MongoDB indexes...")

        results["users"] = await self.create_users_indexes()
        results["departments"] = await self.create_departments_indexes()

        print("MongoDB indexes checked/created successfully")

        return results

    # -------------------------
    # Users indexes
    # -------------------------

    async def create_users_indexes(self) -> Dict[str, Any]:
        """
        Create indexes for users collection.

        Indexes:
        1. username unique
        2. email unique
        3. phone unique sparse
        4. is_active + created_at
        5. role
        6. locked_until sparse
        7. last_login sparse
        """
        collection = self.db.users
        created_or_verified: List[str] = []

        index_definitions = [
            {
                "keys": [("username", ASCENDING)],
                "name": "idx_username_unique",
                "unique": True,
            },
            {
                "keys": [("email", ASCENDING)],
                "name": "idx_email_unique",
                "unique": True,
            },
            {
                "keys": [("phone", ASCENDING)],
                "name": "idx_phone_unique_sparse",
                "unique": True,
                "sparse": True,
            },
            {
                "keys": [("is_active", ASCENDING), ("created_at", DESCENDING)],
                "name": "idx_users_active_created",
            },
            {
                "keys": [("role", ASCENDING)],
                "name": "idx_users_role",
            },
            {
                "keys": [("locked_until", ASCENDING)],
                "name": "idx_users_locked_until_sparse",
                "sparse": True,
            },
            {
                "keys": [("last_login", DESCENDING)],
                "name": "idx_users_last_login",
                "sparse": True,
            },
        ]

        for index in index_definitions:
            try:
                index_name = await collection.create_index(
                    index["keys"],
                    name=index["name"],
                    unique=index.get("unique", False),
                    sparse=index.get("sparse", False),
                )
                created_or_verified.append(index_name)

            except Exception as exc:
                print(f"Failed to create/check users index {index['name']}: {exc}")

        print(f"Users collection: {len(created_or_verified)} indexes checked/created")

        return {
            "collection": "users",
            "indexes": created_or_verified,
            "total": len(created_or_verified),
        }

    # -------------------------
    # Departments indexes
    # -------------------------

    async def create_departments_indexes(self) -> Dict[str, Any]:
        """
        Create indexes for departments collection.

        Indexes:
        1. code unique
        2. is_active + display_order
        3. parent_id + is_active
        4. location + is_active
        5. name
        6. text search index for name/code/description/location

        Why unique code matters:
        DepartmentRepository catches DuplicateKeyError during create.
        That DuplicateKeyError only happens reliably if MongoDB has a unique
        index on departments.code.
        """
        collection = self.db.departments
        created_or_verified: List[str] = []

        index_definitions = [
            {
                "keys": [("code", ASCENDING)],
                "name": "idx_departments_code_unique",
                "unique": True,
            },
            {
                "keys": [("is_active", ASCENDING), ("display_order", ASCENDING)],
                "name": "idx_departments_active_display_order",
            },
            {
                "keys": [("parent_id", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_departments_parent_active",
            },
            {
                "keys": [("location", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_departments_location_active",
            },
            {
                "keys": [("name", ASCENDING)],
                "name": "idx_departments_name",
            },
            {
                "keys": [
                    ("name", TEXT),
                    ("code", TEXT),
                    ("description", TEXT),
                    ("location", TEXT),
                ],
                "name": "idx_departments_text_search",
            },
        ]

        for index in index_definitions:
            try:
                index_name = await collection.create_index(
                    index["keys"],
                    name=index["name"],
                    unique=index.get("unique", False),
                    sparse=index.get("sparse", False),
                )
                created_or_verified.append(index_name)

            except Exception as exc:
                print(f"Failed to create/check departments index {index['name']}: {exc}")

        print(
            f"Departments collection: {len(created_or_verified)} indexes checked/created"
        )

        return {
            "collection": "departments",
            "indexes": created_or_verified,
            "total": len(created_or_verified),
        }

    # -------------------------
    # Development/debug helpers
    # -------------------------

    async def drop_all_indexes(self, collection_name: str) -> bool:
        """
        Drop all indexes except the default _id index.

        WARNING:
        Use only during development/testing.
        Do not use casually in production.
        """
        try:
            collection = self.db[collection_name]
            await collection.drop_indexes()
            print(f"Dropped indexes from collection: {collection_name}")
            return True

        except Exception as exc:
            print(f"Failed to drop indexes from {collection_name}: {exc}")
            return False

    async def list_indexes(self, collection_name: str) -> List[Dict[str, Any]]:
        """
        List all indexes for a collection.

        Useful for debugging.
        """
        try:
            collection = self.db[collection_name]
            indexes = await collection.list_indexes().to_list(length=None)
            return indexes

        except Exception as exc:
            print(f"Failed to list indexes for {collection_name}: {exc}")
            return []


async def create_indexes(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    """
    Main function called during FastAPI startup.

    Usage in main.py:
        db = MongoDB.get_database()
        await create_indexes(db)
    """
    manager = IndexManager(db)
    return await manager.create_all_indexes()


async def drop_indexes(db: AsyncIOMotorDatabase, collection_name: str) -> bool:
    """
    Drop all indexes for a collection.

    Development/testing only.
    """
    manager = IndexManager(db)
    return await manager.drop_all_indexes(collection_name)


async def list_collection_indexes(
    db: AsyncIOMotorDatabase,
    collection_name: str,
) -> List[Dict[str, Any]]:
    """
    List indexes for a specific collection.
    """
    manager = IndexManager(db)
    return await manager.list_indexes(collection_name)