"""
MongoDB index creation for project collections.

Indexes are created at application startup to ensure:
- Unique usernames and emails
- Fast login/admin queries
- Unique department codes
- Unique designation codes
- Unique leave type codes
- Unique claim type codes
- Unique holiday date/name/location records
- Fast master data listing, filtering, searching, and hierarchy lookups

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
        results["designations"] = await self.create_designations_indexes()
        results["leave_types"] = await self.create_leave_types_indexes()
        results["claim_types"] = await self.create_claim_types_indexes()
        results["holidays"] = await self.create_holidays_indexes()

        print("MongoDB indexes checked/created successfully")

        return results

    async def _create_indexes_for_collection(
        self,
        collection_name: str,
        index_definitions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Shared helper for creating indexes safely.
        """
        collection = self.db[collection_name]
        created_or_verified: List[str] = []
        errors: List[Dict[str, str]] = []

        for index in index_definitions:
            try:
                index_name = await collection.create_index(
                    index["keys"],
                    name=index["name"],
                    unique=index.get("unique", False),
                    sparse=index.get("sparse", False),
                    background=index.get("background", True),
                )
                created_or_verified.append(index_name)

            except Exception as exc:
                error = {
                    "index": index["name"],
                    "error": str(exc),
                }
                errors.append(error)
                print(
                    f"Failed to create/check {collection_name} index "
                    f"{index['name']}: {exc}"
                )

        print(
            f"{collection_name} collection: "
            f"{len(created_or_verified)} indexes checked/created"
        )

        return {
            "collection": collection_name,
            "indexes": created_or_verified,
            "total": len(created_or_verified),
            "errors": errors,
        }

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

        return await self._create_indexes_for_collection(
            collection_name="users",
            index_definitions=index_definitions,
        )

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
        """
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

        return await self._create_indexes_for_collection(
            collection_name="departments",
            index_definitions=index_definitions,
        )

    # -------------------------
    # Designations indexes
    # -------------------------

    async def create_designations_indexes(self) -> Dict[str, Any]:
        """
        Create indexes for designations collection.

        Indexes:
        1. code unique
        2. is_active + display_order
        3. department_id + is_active
        4. level + is_active
        5. name
        6. text search index for name/code/description
        """
        index_definitions = [
            {
                "keys": [("code", ASCENDING)],
                "name": "idx_designations_code_unique",
                "unique": True,
            },
            {
                "keys": [("is_active", ASCENDING), ("display_order", ASCENDING)],
                "name": "idx_designations_active_display_order",
            },
            {
                "keys": [("department_id", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_designations_department_active",
            },
            {
                "keys": [("level", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_designations_level_active",
            },
            {
                "keys": [("name", ASCENDING)],
                "name": "idx_designations_name",
            },
            {
                "keys": [
                    ("name", TEXT),
                    ("code", TEXT),
                    ("description", TEXT),
                ],
                "name": "idx_designations_text_search",
            },
        ]

        return await self._create_indexes_for_collection(
            collection_name="designations",
            index_definitions=index_definitions,
        )

    # -------------------------
    # Leave Types indexes
    # -------------------------

    async def create_leave_types_indexes(self) -> Dict[str, Any]:
        """
        Create indexes for leave_types collection.

        Indexes:
        1. code unique
        2. is_active + display_order
        3. is_paid + is_active
        4. requires_approval + is_active
        5. requires_documentation + is_active
        6. carry_forward_allowed + is_active
        7. encashment_allowed + is_active
        8. is_accrued + is_active
        9. available_during_probation + is_active
        10. gender_specific + is_active
        11. name
        12. text search index for name/code/description
        """
        index_definitions = [
            {
                "keys": [("code", ASCENDING)],
                "name": "idx_leave_types_code_unique",
                "unique": True,
            },
            {
                "keys": [("is_active", ASCENDING), ("display_order", ASCENDING)],
                "name": "idx_leave_types_active_display_order",
            },
            {
                "keys": [("is_paid", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_leave_types_paid_active",
            },
            {
                "keys": [("requires_approval", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_leave_types_approval_active",
            },
            {
                "keys": [
                    ("requires_documentation", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                "name": "idx_leave_types_documentation_active",
            },
            {
                "keys": [
                    ("carry_forward_allowed", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                "name": "idx_leave_types_carry_forward_active",
            },
            {
                "keys": [("encashment_allowed", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_leave_types_encashment_active",
            },
            {
                "keys": [("is_accrued", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_leave_types_accrued_active",
            },
            {
                "keys": [
                    ("available_during_probation", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                "name": "idx_leave_types_probation_active",
            },
            {
                "keys": [("gender_specific", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_leave_types_gender_active",
                "sparse": True,
            },
            {
                "keys": [("name", ASCENDING)],
                "name": "idx_leave_types_name",
            },
            {
                "keys": [
                    ("name", TEXT),
                    ("code", TEXT),
                    ("description", TEXT),
                ],
                "name": "idx_leave_types_text_search",
            },
        ]

        return await self._create_indexes_for_collection(
            collection_name="leave_types",
            index_definitions=index_definitions,
        )

    # -------------------------
    # Claim Types indexes
    # -------------------------

    async def create_claim_types_indexes(self) -> Dict[str, Any]:
        """
        Create indexes for claim_types collection.

        Indexes:
        1. code unique
        2. is_active + display_order
        3. requires_bill + is_active
        4. requires_approval + is_active
        5. is_taxable + is_active
        6. currency + is_active
        7. available_during_probation + is_active
        8. auto_approve_below + is_active
        9. finance_approval_threshold + is_active
        10. default_annual_limit
        11. default_monthly_limit
        12. max_claim_amount
        13. name
        14. text search index for name/code/description

        Why unique code matters:
        ClaimTypeRepository catches DuplicateKeyError during create.
        That DuplicateKeyError only happens reliably if MongoDB has a unique
        index on claim_types.code.
        """
        index_definitions = [
            {
                "keys": [("code", ASCENDING)],
                "name": "idx_claim_types_code_unique",
                "unique": True,
            },
            {
                "keys": [("is_active", ASCENDING), ("display_order", ASCENDING)],
                "name": "idx_claim_types_active_display_order",
            },
            {
                "keys": [("requires_bill", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_claim_types_requires_bill_active",
            },
            {
                "keys": [("requires_approval", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_claim_types_requires_approval_active",
            },
            {
                "keys": [("is_taxable", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_claim_types_taxable_active",
            },
            {
                "keys": [("currency", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_claim_types_currency_active",
            },
            {
                "keys": [
                    ("available_during_probation", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                "name": "idx_claim_types_probation_active",
            },
            {
                "keys": [("auto_approve_below", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_claim_types_auto_approve_active",
                "sparse": True,
            },
            {
                "keys": [
                    ("finance_approval_threshold", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                "name": "idx_claim_types_finance_approval_active",
                "sparse": True,
            },
            {
                "keys": [("default_annual_limit", ASCENDING)],
                "name": "idx_claim_types_annual_limit",
            },
            {
                "keys": [("default_monthly_limit", ASCENDING)],
                "name": "idx_claim_types_monthly_limit",
                "sparse": True,
            },
            {
                "keys": [("max_claim_amount", ASCENDING)],
                "name": "idx_claim_types_max_claim_amount",
                "sparse": True,
            },
            {
                "keys": [("name", ASCENDING)],
                "name": "idx_claim_types_name",
            },
            {
                "keys": [
                    ("name", TEXT),
                    ("code", TEXT),
                    ("description", TEXT),
                ],
                "name": "idx_claim_types_text_search",
            },
        ]

        return await self._create_indexes_for_collection(
            collection_name="claim_types",
            index_definitions=index_definitions,
        )

    # -------------------------
    # Holidays indexes
    # -------------------------

    async def create_holidays_indexes(self) -> Dict[str, Any]:
        """
        Create indexes for holidays collection.

        Indexes:
        1. unique date + name + location
        2. year + date
        3. active + date
        4. date + active
        5. location + active
        6. type + active
        7. optional + active
        8. working day + active
        9. half day + active
        10. display order + date
        11. name
        12. text search index for name/type/description/location

        Why unique date/name/location matters:
        HolidayRepository checks duplicate_exists(date, name, location).
        This unique index protects the database level too.
        """
        index_definitions = [
            {
                "keys": [
                    ("date", ASCENDING),
                    ("name", ASCENDING),
                    ("location", ASCENDING),
                ],
                "name": "idx_holidays_date_name_location_unique",
                "unique": True,
            },
            {
                "keys": [("year", ASCENDING), ("date", ASCENDING)],
                "name": "idx_holidays_year_date",
            },
            {
                "keys": [("is_active", ASCENDING), ("date", ASCENDING)],
                "name": "idx_holidays_active_date",
            },
            {
                "keys": [("date", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_holidays_date_active",
            },
            {
                "keys": [("location", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_holidays_location_active",
            },
            {
                "keys": [("type", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_holidays_type_active",
            },
            {
                "keys": [("is_optional", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_holidays_optional_active",
            },
            {
                "keys": [("is_working_day", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_holidays_working_day_active",
            },
            {
                "keys": [("is_half_day", ASCENDING), ("is_active", ASCENDING)],
                "name": "idx_holidays_half_day_active",
            },
            {
                "keys": [("display_order", ASCENDING), ("date", ASCENDING)],
                "name": "idx_holidays_display_order_date",
            },
            {
                "keys": [("name", ASCENDING)],
                "name": "idx_holidays_name",
            },
            {
                "keys": [
                    ("name", TEXT),
                    ("type", TEXT),
                    ("description", TEXT),
                    ("location", TEXT),
                ],
                "name": "idx_holidays_text_search",
            },
        ]

        return await self._create_indexes_for_collection(
            collection_name="holidays",
            index_definitions=index_definitions,
        )

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