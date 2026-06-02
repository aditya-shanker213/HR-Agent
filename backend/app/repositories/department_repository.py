"""
Department repository - all MongoDB operations for departments collection.

Pattern:
Route → Service → Repository → MongoDB

This repository handles:
- Create department
- Read department by id/code
- List departments with filters/search/pagination
- Count departments for pagination
- Update department
- Activate/deactivate department
- Bulk import support
- Department statistics

Important:
- Routes should not write MongoDB queries.
- Services should not write MongoDB queries.
- All department collection queries should go through this repository.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import re

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError


class DepartmentRepository:
    """
    Repository for departments collection.

    This class is responsible only for database operations.
    Business rules should stay in service layer.
    """

    VALID_SORT_FIELDS = {
        "display_order",
        "name",
        "code",
        "created_at",
        "updated_at",
    }

    BLOCKED_UPDATE_FIELDS = {
        "_id",
        "id",
        "created_at",
        "created_by",
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.departments

    # -------------------------
    # Internal helpers
    # -------------------------

    def _normalize_code(self, code: str) -> str:
        """Normalize department code to uppercase."""
        return code.strip().upper()

    def _normalize_optional_text(self, value: Optional[str]) -> Optional[str]:
        """Strip optional text and convert empty string to None."""
        if value is None:
            return None

        value = value.strip()
        return value or None

    def _to_object_id(self, value: str) -> Optional[ObjectId]:
        """Safely convert string ID to MongoDB ObjectId."""
        try:
            return ObjectId(value)
        except (InvalidId, TypeError):
            return None

    def _convert_id(self, document: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Convert MongoDB ObjectId to string.

        Keeps both:
        - _id for internal consistency
        - id for API/service convenience
        """
        if document and "_id" in document:
            document["_id"] = str(document["_id"])
            document["id"] = document["_id"]

        return document

    def _convert_many_ids(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert ObjectId to string for a list of documents."""
        return [self._convert_id(doc) for doc in documents if doc is not None]

    def _clean_update_data(self, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove fields that should never be updated directly.
        Normalize code and optional text fields.
        """
        cleaned: Dict[str, Any] = {}

        for key, value in update_data.items():
            if key in self.BLOCKED_UPDATE_FIELDS:
                continue

            cleaned[key] = value

        if "code" in cleaned and cleaned["code"] is not None:
            cleaned["code"] = self._normalize_code(cleaned["code"])

        for field in ["description", "head_id", "parent_id", "location", "updated_by"]:
            if field in cleaned:
                cleaned[field] = self._normalize_optional_text(cleaned[field])

        cleaned["updated_at"] = datetime.utcnow()

        return cleaned

    def _build_filter_query(
        self,
        is_active: Optional[bool] = None,
        location: Optional[str] = None,
        parent_id: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build MongoDB query for list/count operations.
        """
        query: Dict[str, Any] = {}

        if is_active is not None:
            query["is_active"] = is_active

        if location:
            query["location"] = location.strip()

        if parent_id:
            query["parent_id"] = parent_id.strip()

        if search:
            safe_search = re.escape(search.strip())
            query["$or"] = [
                {"name": {"$regex": safe_search, "$options": "i"}},
                {"code": {"$regex": safe_search.upper(), "$options": "i"}},
                {"description": {"$regex": safe_search, "$options": "i"}},
                {"location": {"$regex": safe_search, "$options": "i"}},
            ]

        return query

    # -------------------------
    # Create
    # -------------------------

    async def create(self, department_data: Dict[str, Any]) -> str:
        """
        Create a new department.

        Returns:
            Created department _id as string.

        Raises:
            DuplicateKeyError if department code already exists.
        """
        now = datetime.utcnow()

        if "code" in department_data:
            department_data["code"] = self._normalize_code(department_data["code"])

        for field in ["description", "head_id", "parent_id", "location", "created_by", "updated_by"]:
            if field in department_data:
                department_data[field] = self._normalize_optional_text(department_data[field])

        department_data.setdefault("is_active", True)
        department_data.setdefault("display_order", 0)

        department_data["created_at"] = now
        department_data["updated_at"] = now

        result = await self.collection.insert_one(department_data)
        return str(result.inserted_id)

    # -------------------------
    # Find operations
    # -------------------------

    async def find_by_id(self, department_id: str) -> Optional[Dict[str, Any]]:
        """Find department by MongoDB _id."""
        object_id = self._to_object_id(department_id)

        if object_id is None:
            return None

        department = await self.collection.find_one({"_id": object_id})
        return self._convert_id(department)

    async def find_active_by_id(self, department_id: str) -> Optional[Dict[str, Any]]:
        """Find active department by MongoDB _id."""
        object_id = self._to_object_id(department_id)

        if object_id is None:
            return None

        department = await self.collection.find_one(
            {
                "_id": object_id,
                "is_active": True,
            }
        )

        return self._convert_id(department)

    async def find_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Find department by unique code."""
        department = await self.collection.find_one(
            {"code": self._normalize_code(code)}
        )

        return self._convert_id(department)

    async def exists_by_id(self, department_id: str) -> bool:
        """Check whether department exists by ID."""
        object_id = self._to_object_id(department_id)

        if object_id is None:
            return False

        count = await self.collection.count_documents({"_id": object_id}, limit=1)
        return count > 0

    async def active_exists_by_id(self, department_id: str) -> bool:
        """Check whether active department exists by ID."""
        object_id = self._to_object_id(department_id)

        if object_id is None:
            return False

        count = await self.collection.count_documents(
            {
                "_id": object_id,
                "is_active": True,
            },
            limit=1,
        )

        return count > 0

    async def code_exists(
        self,
        code: str,
        exclude_id: Optional[str] = None,
    ) -> bool:
        """
        Check whether department code already exists.

        exclude_id is used during update so the same department can keep its code.
        """
        query: Dict[str, Any] = {
            "code": self._normalize_code(code),
        }

        if exclude_id:
            object_id = self._to_object_id(exclude_id)
            if object_id is not None:
                query["_id"] = {"$ne": object_id}

        count = await self.collection.count_documents(query, limit=1)
        return count > 0

    # -------------------------
    # List and search
    # -------------------------

    async def list_all(
        self,
        is_active: Optional[bool] = None,
        location: Optional[str] = None,
        parent_id: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "display_order",
        sort_order: str = "asc",
        skip: int = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List departments with filtering, search, sorting, and pagination.
        """
        query = self._build_filter_query(
            is_active=is_active,
            location=location,
            parent_id=parent_id,
            search=search,
        )

        if sort_by not in self.VALID_SORT_FIELDS:
            sort_by = "display_order"

        sort_direction = ASCENDING if sort_order.lower() == "asc" else DESCENDING

        safe_skip = max(skip, 0)
        safe_limit = min(max(limit, 1), 100)

        cursor = (
            self.collection.find(query)
            .sort(sort_by, sort_direction)
            .skip(safe_skip)
            .limit(safe_limit)
        )

        departments = await cursor.to_list(length=safe_limit)
        return self._convert_many_ids(departments)

    async def count(
        self,
        is_active: Optional[bool] = None,
        location: Optional[str] = None,
        parent_id: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        """
        Count departments matching filters.

        Useful for pagination metadata.
        """
        query = self._build_filter_query(
            is_active=is_active,
            location=location,
            parent_id=parent_id,
            search=search,
        )

        return await self.collection.count_documents(query)

    async def get_children_count(self, department_id: str) -> int:
        """
        Count active child departments.
        """
        return await self.collection.count_documents(
            {
                "parent_id": department_id,
                "is_active": True,
            }
        )

    async def has_active_children(self, department_id: str) -> bool:
        """
        Check whether department has active child departments.

        Useful before deactivating a parent department.
        """
        count = await self.get_children_count(department_id)
        return count > 0

    # -------------------------
    # Update
    # -------------------------

    async def update(
        self,
        department_id: str,
        update_data: Dict[str, Any],
    ) -> bool:
        """
        Update department fields.

        Returns:
            True if department exists and update operation matched it.
        """
        object_id = self._to_object_id(department_id)

        if object_id is None:
            return False

        safe_update = self._clean_update_data(update_data)

        if not safe_update:
            return False

        result = await self.collection.update_one(
            {"_id": object_id},
            {"$set": safe_update},
        )

        return result.matched_count > 0

    # -------------------------
    # Activate / deactivate
    # -------------------------

    async def deactivate(
        self,
        department_id: str,
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Soft delete department by setting is_active=False.

        The document remains in MongoDB.
        """
        object_id = self._to_object_id(department_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "is_active": False,
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = updated_by

        result = await self.collection.update_one(
            {"_id": object_id},
            {"$set": update_data},
        )

        return result.matched_count > 0

    async def activate(
        self,
        department_id: str,
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Reactivate a deactivated department.
        """
        object_id = self._to_object_id(department_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "is_active": True,
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = updated_by

        result = await self.collection.update_one(
            {"_id": object_id},
            {"$set": update_data},
        )

        return result.matched_count > 0

    # -------------------------
    # Bulk operations
    # -------------------------

    async def create_many(
        self,
        departments: List[Dict[str, Any]],
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Create multiple departments.

        Returns:
            Tuple of:
            - created_ids
            - errors

        This keeps per-record error reporting, useful for bulk import UI.
        """
        created_ids: List[str] = []
        errors: List[Dict[str, Any]] = []

        for index, department_data in enumerate(departments):
            try:
                created_id = await self.create(department_data)
                created_ids.append(created_id)

            except DuplicateKeyError:
                errors.append(
                    {
                        "index": index,
                        "code": department_data.get("code"),
                        "error": "Department code already exists",
                    }
                )

            except Exception as exc:
                errors.append(
                    {
                        "index": index,
                        "code": department_data.get("code"),
                        "error": str(exc),
                    }
                )

        return created_ids, errors

    # -------------------------
    # Statistics
    # -------------------------

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get department statistics for admin dashboard.
        """
        total = await self.collection.count_documents({})
        active = await self.collection.count_documents({"is_active": True})
        inactive = total - active

        location_pipeline = [
            {
                "$match": {
                    "is_active": True,
                    "location": {
                        "$nin": [None, ""],
                    },
                }
            },
            {
                "$group": {
                    "_id": "$location",
                    "count": {"$sum": 1},
                }
            },
            {
                "$sort": {
                    "count": -1,
                }
            },
        ]

        locations = await self.collection.aggregate(location_pipeline).to_list(None)

        return {
            "total": total,
            "active": active,
            "inactive": inactive,
            "by_location": [
                {
                    "location": item["_id"],
                    "count": item["count"],
                }
                for item in locations
            ],
        }