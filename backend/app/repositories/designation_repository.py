"""
Designation repository - all MongoDB operations for designations collection.

Pattern:
Route → Service → Repository → MongoDB

This repository handles:
- Create designation
- Read designation by id/code
- List designations with filters/search/pagination
- Count designations for pagination
- Update designation
- Activate/deactivate designation
- Bulk import support
- Dropdown/list helpers
- Designation statistics

Important:
- Routes should not write MongoDB queries.
- Services should not write MongoDB queries.
- All designation collection queries should go through this repository.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import re

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError


class DesignationRepository:
    """
    Repository for designations collection.

    This class is responsible only for database operations.
    Business rules should stay in service layer.
    """

    VALID_SORT_FIELDS = {
        "display_order",
        "name",
        "code",
        "level",
        "department_id",
        "created_at",
        "updated_at",
    }

    BLOCKED_UPDATE_FIELDS = {
        "_id",
        "id",
        "created_at",
        "created_by",
    }

    OPTIONAL_TEXT_FIELDS = {
        "description",
        "department_id",
        "created_by",
        "updated_by",
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.designations

    # -------------------------
    # Internal helpers
    # -------------------------

    def _normalize_code(self, code: str) -> str:
        """
        Normalize designation code to uppercase.
        """
        return code.strip().upper()

    def _normalize_optional_text(self, value: Optional[str]) -> Optional[str]:
        """
        Strip optional text and convert empty string to None.
        """
        if value is None:
            return None

        value = value.strip()
        return value or None

    def _to_object_id(self, value: str) -> Optional[ObjectId]:
        """
        Safely convert string ID to MongoDB ObjectId.
        """
        try:
            return ObjectId(value)
        except (InvalidId, TypeError):
            return None

    def _convert_id(
        self,
        document: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
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

    def _convert_many_ids(
        self,
        documents: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Convert ObjectId to string for a list of documents.
        """
        return [self._convert_id(document) for document in documents if document is not None]

    def _clean_insert_data(self, designation_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize designation data before insert.
        """
        cleaned = dict(designation_data)

        if "code" in cleaned and cleaned["code"] is not None:
            cleaned["code"] = self._normalize_code(cleaned["code"])

        for field in self.OPTIONAL_TEXT_FIELDS:
            if field in cleaned:
                cleaned[field] = self._normalize_optional_text(cleaned[field])

        cleaned.setdefault("is_active", True)
        cleaned.setdefault("display_order", 0)

        now = datetime.utcnow()
        cleaned["created_at"] = now
        cleaned["updated_at"] = now

        return cleaned

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

        for field in self.OPTIONAL_TEXT_FIELDS:
            if field in cleaned:
                cleaned[field] = self._normalize_optional_text(cleaned[field])

        cleaned["updated_at"] = datetime.utcnow()

        return cleaned

    def _build_filter_query(
        self,
        is_active: Optional[bool] = None,
        department_id: Optional[str] = None,
        level: Optional[int] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build MongoDB query for list/count operations.
        """
        query: Dict[str, Any] = {}

        if is_active is not None:
            query["is_active"] = is_active

        if department_id:
            query["department_id"] = department_id.strip()

        if level is not None:
            query["level"] = level

        if search:
            safe_search = re.escape(search.strip())
            query["$or"] = [
                {"name": {"$regex": safe_search, "$options": "i"}},
                {"code": {"$regex": safe_search.upper(), "$options": "i"}},
                {"description": {"$regex": safe_search, "$options": "i"}},
            ]

        return query

    # -------------------------
    # Create
    # -------------------------

    async def create(self, designation_data: Dict[str, Any]) -> str:
        """
        Create a new designation.

        Returns:
            Created designation _id as string.

        Raises:
            DuplicateKeyError if designation code already exists.
        """
        cleaned_data = self._clean_insert_data(designation_data)

        result = await self.collection.insert_one(cleaned_data)
        return str(result.inserted_id)

    # -------------------------
    # Find operations
    # -------------------------

    async def find_by_id(self, designation_id: str) -> Optional[Dict[str, Any]]:
        """
        Find designation by MongoDB _id.
        """
        object_id = self._to_object_id(designation_id)

        if object_id is None:
            return None

        designation = await self.collection.find_one({"_id": object_id})
        return self._convert_id(designation)

    async def find_active_by_id(
        self,
        designation_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Find active designation by MongoDB _id.
        """
        object_id = self._to_object_id(designation_id)

        if object_id is None:
            return None

        designation = await self.collection.find_one(
            {
                "_id": object_id,
                "is_active": True,
            }
        )

        return self._convert_id(designation)

    async def find_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Find designation by unique code.
        """
        designation = await self.collection.find_one(
            {
                "code": self._normalize_code(code),
            }
        )

        return self._convert_id(designation)

    async def find_active_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Find active designation by unique code.
        """
        designation = await self.collection.find_one(
            {
                "code": self._normalize_code(code),
                "is_active": True,
            }
        )

        return self._convert_id(designation)

    async def exists_by_id(self, designation_id: str) -> bool:
        """
        Check whether designation exists by ID.
        """
        object_id = self._to_object_id(designation_id)

        if object_id is None:
            return False

        count = await self.collection.count_documents(
            {"_id": object_id},
            limit=1,
        )

        return count > 0

    async def active_exists_by_id(self, designation_id: str) -> bool:
        """
        Check whether active designation exists by ID.
        """
        object_id = self._to_object_id(designation_id)

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
        Check whether designation code already exists.

        exclude_id is used during update so the same designation can keep its code.
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
        department_id: Optional[str] = None,
        level: Optional[int] = None,
        search: Optional[str] = None,
        sort_by: str = "display_order",
        sort_order: str = "asc",
        skip: int = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List designations with filtering, search, sorting, and pagination.
        """
        query = self._build_filter_query(
            is_active=is_active,
            department_id=department_id,
            level=level,
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

        designations = await cursor.to_list(length=safe_limit)
        return self._convert_many_ids(designations)

    async def list_active_for_dropdown(
        self,
        department_id: Optional[str] = None,
        include_global: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List active designations for frontend dropdowns.

        If department_id is provided and include_global=True:
        - returns department-specific designations
        - plus global designations where department_id is None

        This is useful because some titles may be department-specific
        while others like Manager or Intern may be cross-department.
        """
        query: Dict[str, Any] = {
            "is_active": True,
        }

        if department_id:
            if include_global:
                query["$or"] = [
                    {"department_id": department_id.strip()},
                    {"department_id": None},
                    {"department_id": ""},
                ]
            else:
                query["department_id"] = department_id.strip()

        cursor = (
            self.collection.find(query)
            .sort("display_order", ASCENDING)
            .sort("name", ASCENDING)
        )

        designations = await cursor.to_list(length=500)
        return self._convert_many_ids(designations)

    async def list_by_department(
        self,
        department_id: str,
        is_active: Optional[bool] = True,
    ) -> List[Dict[str, Any]]:
        """
        List designations linked to a specific department.
        """
        query: Dict[str, Any] = {
            "department_id": department_id.strip(),
        }

        if is_active is not None:
            query["is_active"] = is_active

        cursor = (
            self.collection.find(query)
            .sort("display_order", ASCENDING)
            .sort("name", ASCENDING)
        )

        designations = await cursor.to_list(length=500)
        return self._convert_many_ids(designations)

    async def count(
        self,
        is_active: Optional[bool] = None,
        department_id: Optional[str] = None,
        level: Optional[int] = None,
        search: Optional[str] = None,
    ) -> int:
        """
        Count designations matching filters.

        Useful for pagination metadata.
        """
        query = self._build_filter_query(
            is_active=is_active,
            department_id=department_id,
            level=level,
            search=search,
        )

        return await self.collection.count_documents(query)

    async def count_by_department(
        self,
        department_id: str,
        is_active: Optional[bool] = True,
    ) -> int:
        """
        Count designations for a department.

        Useful later for validation or dashboard metrics.
        """
        query: Dict[str, Any] = {
            "department_id": department_id.strip(),
        }

        if is_active is not None:
            query["is_active"] = is_active

        return await self.collection.count_documents(query)

    # -------------------------
    # Update
    # -------------------------

    async def update(
        self,
        designation_id: str,
        update_data: Dict[str, Any],
    ) -> bool:
        """
        Update designation fields.

        Returns:
            True if designation exists and update operation matched it.
        """
        object_id = self._to_object_id(designation_id)

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
        designation_id: str,
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Soft delete designation by setting is_active=False.

        The document remains in MongoDB.
        """
        object_id = self._to_object_id(designation_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "is_active": False,
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

        result = await self.collection.update_one(
            {"_id": object_id},
            {"$set": update_data},
        )

        return result.matched_count > 0

    async def activate(
        self,
        designation_id: str,
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Reactivate a deactivated designation.
        """
        object_id = self._to_object_id(designation_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "is_active": True,
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

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
        designations: List[Dict[str, Any]],
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Create multiple designations.

        Returns:
            Tuple of:
            - created_ids
            - errors

        This keeps per-record error reporting, useful for bulk import UI.
        """
        created_ids: List[str] = []
        errors: List[Dict[str, Any]] = []

        for index, designation_data in enumerate(designations):
            try:
                created_id = await self.create(designation_data)
                created_ids.append(created_id)

            except DuplicateKeyError:
                errors.append(
                    {
                        "index": index,
                        "code": designation_data.get("code"),
                        "error": "Designation code already exists",
                    }
                )

            except Exception as exc:
                errors.append(
                    {
                        "index": index,
                        "code": designation_data.get("code"),
                        "error": str(exc),
                    }
                )

        return created_ids, errors

    # -------------------------
    # Statistics
    # -------------------------

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get designation statistics for admin dashboard.
        """
        total = await self.collection.count_documents({})
        active = await self.collection.count_documents({"is_active": True})
        inactive = total - active

        level_pipeline = [
            {
                "$match": {
                    "is_active": True,
                    "level": {
                        "$nin": [None, ""],
                    },
                }
            },
            {
                "$group": {
                    "_id": "$level",
                    "count": {"$sum": 1},
                }
            },
            {
                "$sort": {
                    "_id": 1,
                }
            },
        ]

        department_pipeline = [
            {
                "$match": {
                    "is_active": True,
                    "department_id": {
                        "$nin": [None, ""],
                    },
                }
            },
            {
                "$group": {
                    "_id": "$department_id",
                    "count": {"$sum": 1},
                }
            },
            {
                "$sort": {
                    "count": -1,
                }
            },
        ]

        levels = await self.collection.aggregate(level_pipeline).to_list(None)
        departments = await self.collection.aggregate(department_pipeline).to_list(None)

        global_count = await self.collection.count_documents(
            {
                "is_active": True,
                "$or": [
                    {"department_id": None},
                    {"department_id": ""},
                    {"department_id": {"$exists": False}},
                ],
            }
        )

        return {
            "total": total,
            "active": active,
            "inactive": inactive,
            "global": global_count,
            "by_level": [
                {
                    "level": item["_id"],
                    "count": item["count"],
                }
                for item in levels
            ],
            "by_department": [
                {
                    "department_id": item["_id"],
                    "count": item["count"],
                }
                for item in departments
            ],
        }