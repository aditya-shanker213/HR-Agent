"""
Leave Type repository - all MongoDB operations for leave_types collection.

Pattern:
Route → Service → Repository → MongoDB

This repository handles:
- Create leave type
- Read leave type by id/code
- List leave types with filters/search/pagination
- Count leave types for pagination
- Update leave type
- Activate/deactivate leave type
- Bulk import support
- Dropdown/list helpers
- Leave type statistics

Important:
- Routes should not write MongoDB queries.
- Services should not write MongoDB queries.
- All leave_types collection queries should go through this repository.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import re

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError


class LeaveTypeRepository:
    """
    Repository for leave_types collection.

    This class is responsible only for database operations.
    Business rules should stay in service layer.
    """

    VALID_SORT_FIELDS = {
        "display_order",
        "name",
        "code",
        "default_annual_grant",
        "max_annual_limit",
        "min_notice_days",
        "is_paid",
        "requires_approval",
        "requires_documentation",
        "carry_forward_allowed",
        "encashment_allowed",
        "is_accrued",
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
        "gender_specific",
        "created_by",
        "updated_by",
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.leave_types

    # -------------------------
    # Internal helpers
    # -------------------------

    def _normalize_code(self, code: str) -> str:
        """
        Normalize leave type code to uppercase.
        """
        return code.strip().upper()

    def _normalize_optional_text(self, value: Optional[str]) -> Optional[str]:
        """
        Strip optional text and convert empty string to None.
        """
        if value is None:
            return None

        value = str(value).strip()
        return value or None

    def _normalize_gender(self, gender: Optional[str]) -> Optional[str]:
        """
        Normalize gender value.

        Accepted values:
        - male
        - female
        - None
        """
        if gender is None:
            return None

        gender = gender.strip().lower()
        return gender or None

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
        return [
            converted
            for document in documents
            if document is not None
            for converted in [self._convert_id(document)]
            if converted is not None
        ]

    def _clean_insert_data(self, leave_type_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize leave type data before insert.
        """
        cleaned = dict(leave_type_data)

        if "code" in cleaned and cleaned["code"] is not None:
            cleaned["code"] = self._normalize_code(cleaned["code"])

        for field in self.OPTIONAL_TEXT_FIELDS:
            if field in cleaned:
                cleaned[field] = self._normalize_optional_text(cleaned[field])

        if "gender_specific" in cleaned:
            cleaned["gender_specific"] = self._normalize_gender(
                cleaned.get("gender_specific")
            )

        cleaned.setdefault("is_active", True)
        cleaned.setdefault("display_order", 0)

        cleaned.setdefault("requires_approval", True)
        cleaned.setdefault("requires_documentation", False)
        cleaned.setdefault("documentation_threshold_days", None)

        cleaned.setdefault("min_notice_days", 0)
        cleaned.setdefault("max_consecutive_days", None)

        cleaned.setdefault("carry_forward_allowed", False)
        cleaned.setdefault("max_carry_forward_days", None)
        cleaned.setdefault("carry_forward_expiry_months", None)

        cleaned.setdefault("is_paid", True)
        cleaned.setdefault("encashment_allowed", False)
        cleaned.setdefault("max_encashment_days", None)

        cleaned.setdefault("is_accrued", False)
        cleaned.setdefault("accrual_rate_per_month", None)

        cleaned.setdefault("available_during_probation", True)
        cleaned.setdefault("probation_grant_percentage", None)

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

        if "gender_specific" in cleaned:
            cleaned["gender_specific"] = self._normalize_gender(
                cleaned.get("gender_specific")
            )

        cleaned["updated_at"] = datetime.utcnow()

        return cleaned

    def _build_filter_query(
        self,
        is_active: Optional[bool] = None,
        is_paid: Optional[bool] = None,
        requires_approval: Optional[bool] = None,
        requires_documentation: Optional[bool] = None,
        carry_forward_allowed: Optional[bool] = None,
        encashment_allowed: Optional[bool] = None,
        is_accrued: Optional[bool] = None,
        available_during_probation: Optional[bool] = None,
        gender_specific: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build MongoDB query for list/count operations.
        """
        query: Dict[str, Any] = {}

        if is_active is not None:
            query["is_active"] = is_active

        if is_paid is not None:
            query["is_paid"] = is_paid

        if requires_approval is not None:
            query["requires_approval"] = requires_approval

        if requires_documentation is not None:
            query["requires_documentation"] = requires_documentation

        if carry_forward_allowed is not None:
            query["carry_forward_allowed"] = carry_forward_allowed

        if encashment_allowed is not None:
            query["encashment_allowed"] = encashment_allowed

        if is_accrued is not None:
            query["is_accrued"] = is_accrued

        if available_during_probation is not None:
            query["available_during_probation"] = available_during_probation

        if gender_specific:
            query["gender_specific"] = gender_specific.strip().lower()

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

    async def create(self, leave_type_data: Dict[str, Any]) -> str:
        """
        Create a new leave type.

        Returns:
            Created leave type _id as string.

        Raises:
            DuplicateKeyError if leave type code already exists.
        """
        cleaned_data = self._clean_insert_data(leave_type_data)

        try:
            result = await self.collection.insert_one(cleaned_data)
            return str(result.inserted_id)
        except DuplicateKeyError:
            raise

    # -------------------------
    # Find operations
    # -------------------------

    async def find_by_id(self, leave_type_id: str) -> Optional[Dict[str, Any]]:
        """
        Find leave type by MongoDB _id.
        """
        object_id = self._to_object_id(leave_type_id)

        if object_id is None:
            return None

        leave_type = await self.collection.find_one({"_id": object_id})
        return self._convert_id(leave_type)

    async def find_active_by_id(
        self,
        leave_type_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Find active leave type by MongoDB _id.
        """
        object_id = self._to_object_id(leave_type_id)

        if object_id is None:
            return None

        leave_type = await self.collection.find_one(
            {
                "_id": object_id,
                "is_active": True,
            }
        )

        return self._convert_id(leave_type)

    async def find_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Find leave type by unique code.
        """
        leave_type = await self.collection.find_one(
            {
                "code": self._normalize_code(code),
            }
        )

        return self._convert_id(leave_type)

    async def find_active_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Find active leave type by unique code.
        """
        leave_type = await self.collection.find_one(
            {
                "code": self._normalize_code(code),
                "is_active": True,
            }
        )

        return self._convert_id(leave_type)

    async def exists_by_id(self, leave_type_id: str) -> bool:
        """
        Check whether leave type exists by ID.
        """
        object_id = self._to_object_id(leave_type_id)

        if object_id is None:
            return False

        count = await self.collection.count_documents({"_id": object_id}, limit=1)
        return count > 0

    async def active_exists_by_id(self, leave_type_id: str) -> bool:
        """
        Check whether active leave type exists by ID.
        """
        object_id = self._to_object_id(leave_type_id)

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
        Check whether leave type code already exists.

        exclude_id is used during update so the same leave type can keep its code.
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
        is_paid: Optional[bool] = None,
        requires_approval: Optional[bool] = None,
        requires_documentation: Optional[bool] = None,
        carry_forward_allowed: Optional[bool] = None,
        encashment_allowed: Optional[bool] = None,
        is_accrued: Optional[bool] = None,
        available_during_probation: Optional[bool] = None,
        gender_specific: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "display_order",
        sort_order: str = "asc",
        skip: int = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List leave types with filtering, search, sorting, and pagination.
        """
        query = self._build_filter_query(
            is_active=is_active,
            is_paid=is_paid,
            requires_approval=requires_approval,
            requires_documentation=requires_documentation,
            carry_forward_allowed=carry_forward_allowed,
            encashment_allowed=encashment_allowed,
            is_accrued=is_accrued,
            available_during_probation=available_during_probation,
            gender_specific=gender_specific,
            search=search,
        )

        if sort_by not in self.VALID_SORT_FIELDS:
            sort_by = "display_order"

        sort_direction = ASCENDING if sort_order.lower() == "asc" else DESCENDING

        safe_skip = max(skip, 0)
        safe_limit = min(max(limit, 1), 100)

        cursor = (
            self.collection.find(query)
            .sort([(sort_by, sort_direction), ("name", ASCENDING)])
            .skip(safe_skip)
            .limit(safe_limit)
        )

        leave_types = await cursor.to_list(length=safe_limit)
        return self._convert_many_ids(leave_types)

    async def list_active_for_dropdown(
        self,
        gender: Optional[str] = None,
        include_unpaid: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List active leave types for frontend dropdowns.

        If gender is provided:
        - returns leave types where gender_specific is None
        - OR gender_specific matches the provided gender

        include_unpaid:
        - True: show paid and unpaid leave types
        - False: show only paid leave types
        """
        query: Dict[str, Any] = {
            "is_active": True,
        }

        if not include_unpaid:
            query["is_paid"] = True

        if gender:
            normalized_gender = gender.strip().lower()
            query["$or"] = [
                {"gender_specific": None},
                {"gender_specific": ""},
                {"gender_specific": normalized_gender},
            ]

        cursor = self.collection.find(query).sort(
            [
                ("display_order", ASCENDING),
                ("name", ASCENDING),
            ]
        )

        leave_types = await cursor.to_list(length=500)
        return self._convert_many_ids(leave_types)

    async def list_paid_active(self) -> List[Dict[str, Any]]:
        """
        List active paid leave types.
        """
        cursor = self.collection.find(
            {
                "is_active": True,
                "is_paid": True,
            }
        ).sort(
            [
                ("display_order", ASCENDING),
                ("name", ASCENDING),
            ]
        )

        leave_types = await cursor.to_list(length=500)
        return self._convert_many_ids(leave_types)

    async def list_unpaid_active(self) -> List[Dict[str, Any]]:
        """
        List active unpaid leave types.
        """
        cursor = self.collection.find(
            {
                "is_active": True,
                "is_paid": False,
            }
        ).sort(
            [
                ("display_order", ASCENDING),
                ("name", ASCENDING),
            ]
        )

        leave_types = await cursor.to_list(length=500)
        return self._convert_many_ids(leave_types)

    async def count(
        self,
        is_active: Optional[bool] = None,
        is_paid: Optional[bool] = None,
        requires_approval: Optional[bool] = None,
        requires_documentation: Optional[bool] = None,
        carry_forward_allowed: Optional[bool] = None,
        encashment_allowed: Optional[bool] = None,
        is_accrued: Optional[bool] = None,
        available_during_probation: Optional[bool] = None,
        gender_specific: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        """
        Count leave types matching filters.

        Useful for pagination metadata.
        """
        query = self._build_filter_query(
            is_active=is_active,
            is_paid=is_paid,
            requires_approval=requires_approval,
            requires_documentation=requires_documentation,
            carry_forward_allowed=carry_forward_allowed,
            encashment_allowed=encashment_allowed,
            is_accrued=is_accrued,
            available_during_probation=available_during_probation,
            gender_specific=gender_specific,
            search=search,
        )

        return await self.collection.count_documents(query)

    # -------------------------
    # Update
    # -------------------------

    async def update(
        self,
        leave_type_id: str,
        update_data: Dict[str, Any],
    ) -> bool:
        """
        Update leave type fields.

        Returns:
            True if leave type exists and update operation matched it.
        """
        object_id = self._to_object_id(leave_type_id)

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

    async def update_many_display_order(
        self,
        order_updates: List[Dict[str, Any]],
        updated_by: Optional[str] = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """
        Update display_order for multiple leave types.

        Expected item format:
        {
            "id": "leave_type_id",
            "display_order": 1
        }

        Returns:
            Tuple of:
            - updated_count
            - errors
        """
        updated_count = 0
        errors: List[Dict[str, Any]] = []

        for index, item in enumerate(order_updates):
            leave_type_id = item.get("id") or item.get("_id")
            display_order = item.get("display_order")

            if leave_type_id is None or display_order is None:
                errors.append(
                    {
                        "index": index,
                        "error": "id and display_order are required",
                    }
                )
                continue

            object_id = self._to_object_id(str(leave_type_id))

            if object_id is None:
                errors.append(
                    {
                        "index": index,
                        "id": leave_type_id,
                        "error": "Invalid leave type ID",
                    }
                )
                continue

            update_data: Dict[str, Any] = {
                "display_order": max(int(display_order), 0),
                "updated_at": datetime.utcnow(),
            }

            if updated_by:
                update_data["updated_by"] = self._normalize_optional_text(updated_by)

            result = await self.collection.update_one(
                {"_id": object_id},
                {"$set": update_data},
            )

            if result.matched_count > 0:
                updated_count += 1
            else:
                errors.append(
                    {
                        "index": index,
                        "id": leave_type_id,
                        "error": "Leave type not found",
                    }
                )

        return updated_count, errors

    # -------------------------
    # Activate / deactivate
    # -------------------------

    async def deactivate(
        self,
        leave_type_id: str,
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Soft delete leave type by setting is_active=False.

        The document remains in MongoDB.
        """
        object_id = self._to_object_id(leave_type_id)

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
        leave_type_id: str,
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Reactivate a deactivated leave type.
        """
        object_id = self._to_object_id(leave_type_id)

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
        leave_types: List[Dict[str, Any]],
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Create multiple leave types.

        Returns:
            Tuple of:
            - created_ids
            - errors

        This keeps per-record error reporting, useful for bulk import UI.
        """
        created_ids: List[str] = []
        errors: List[Dict[str, Any]] = []

        for index, leave_type_data in enumerate(leave_types):
            try:
                created_id = await self.create(leave_type_data)
                created_ids.append(created_id)

            except DuplicateKeyError:
                errors.append(
                    {
                        "index": index,
                        "code": leave_type_data.get("code"),
                        "error": "Leave type code already exists",
                    }
                )

            except Exception as exc:
                errors.append(
                    {
                        "index": index,
                        "code": leave_type_data.get("code"),
                        "error": str(exc),
                    }
                )

        return created_ids, errors

    # -------------------------
    # Rule helpers
    # -------------------------

    async def get_leave_rules_by_id(
        self,
        leave_type_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get active leave type rules by ID.

        Used later by leave validation service before applying leave.
        """
        leave_type = await self.find_active_by_id(leave_type_id)

        if not leave_type:
            return None

        return {
            "id": leave_type.get("id") or leave_type.get("_id"),
            "name": leave_type.get("name"),
            "code": leave_type.get("code"),
            "default_annual_grant": leave_type.get("default_annual_grant", 0),
            "max_annual_limit": leave_type.get("max_annual_limit"),
            "requires_approval": leave_type.get("requires_approval", True),
            "requires_documentation": leave_type.get("requires_documentation", False),
            "documentation_threshold_days": leave_type.get(
                "documentation_threshold_days"
            ),
            "min_notice_days": leave_type.get("min_notice_days", 0),
            "max_consecutive_days": leave_type.get("max_consecutive_days"),
            "carry_forward_allowed": leave_type.get("carry_forward_allowed", False),
            "max_carry_forward_days": leave_type.get("max_carry_forward_days"),
            "carry_forward_expiry_months": leave_type.get(
                "carry_forward_expiry_months"
            ),
            "is_paid": leave_type.get("is_paid", True),
            "encashment_allowed": leave_type.get("encashment_allowed", False),
            "max_encashment_days": leave_type.get("max_encashment_days"),
            "is_accrued": leave_type.get("is_accrued", False),
            "accrual_rate_per_month": leave_type.get("accrual_rate_per_month"),
            "gender_specific": leave_type.get("gender_specific"),
            "available_during_probation": leave_type.get(
                "available_during_probation", True
            ),
            "probation_grant_percentage": leave_type.get(
                "probation_grant_percentage"
            ),
        }

    async def get_leave_rules_by_code(
        self,
        code: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get active leave type rules by code.

        Useful when seed data or admin setup uses leave codes.
        """
        leave_type = await self.find_active_by_code(code)

        if not leave_type:
            return None

        leave_type_id = leave_type.get("id") or leave_type.get("_id")
        return await self.get_leave_rules_by_id(leave_type_id)

    # -------------------------
    # Statistics
    # -------------------------

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get leave type statistics for admin dashboard.
        """
        total = await self.collection.count_documents({})
        active = await self.collection.count_documents({"is_active": True})
        inactive = total - active

        paid = await self.collection.count_documents(
            {"is_active": True, "is_paid": True}
        )

        unpaid = await self.collection.count_documents(
            {"is_active": True, "is_paid": False}
        )

        requires_approval = await self.collection.count_documents(
            {"is_active": True, "requires_approval": True}
        )

        no_approval_required = await self.collection.count_documents(
            {"is_active": True, "requires_approval": False}
        )

        requires_documentation = await self.collection.count_documents(
            {"is_active": True, "requires_documentation": True}
        )

        carry_forward_enabled = await self.collection.count_documents(
            {"is_active": True, "carry_forward_allowed": True}
        )

        encashment_enabled = await self.collection.count_documents(
            {"is_active": True, "encashment_allowed": True}
        )

        accrued = await self.collection.count_documents(
            {"is_active": True, "is_accrued": True}
        )

        available_during_probation = await self.collection.count_documents(
            {"is_active": True, "available_during_probation": True}
        )

        gender_specific = await self.collection.count_documents(
            {
                "is_active": True,
                "gender_specific": {"$nin": [None, ""]},
            }
        )

        return {
            "total": total,
            "active": active,
            "inactive": inactive,
            "paid": paid,
            "unpaid": unpaid,
            "requires_approval": requires_approval,
            "no_approval_required": no_approval_required,
            "requires_documentation": requires_documentation,
            "carry_forward_enabled": carry_forward_enabled,
            "encashment_enabled": encashment_enabled,
            "accrued": accrued,
            "available_during_probation": available_during_probation,
            "gender_specific": gender_specific,
        }