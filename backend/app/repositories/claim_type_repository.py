"""
Claim Type repository - all MongoDB operations for claim_types collection.

Pattern:
Route → Service → Repository → MongoDB

This repository handles:
- Create claim type
- Read claim type by id/code
- List claim types with filters/search/pagination
- Count claim types for pagination
- Update claim type
- Activate/deactivate claim type
- Bulk import support
- Dropdown/list helpers
- Claim type rule helpers
- Claim type statistics

Important:
- Routes should not write MongoDB queries.
- Services should not write MongoDB queries.
- All claim_types collection queries should go through this repository.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import re

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError


class ClaimTypeRepository:
    """
    Repository for claim_types collection.

    This class is responsible only for database operations.
    Business rules should stay in service layer.
    """

    DEFAULT_ALLOWED_FILE_TYPES = ["pdf", "jpg", "jpeg", "png"]

    VALID_SORT_FIELDS = {
        "display_order",
        "name",
        "code",
        "default_annual_limit",
        "default_monthly_limit",
        "max_claim_amount",
        "min_claim_amount",
        "requires_bill",
        "requires_approval",
        "is_taxable",
        "currency",
        "created_at",
        "updated_at",
    }

    BLOCKED_UPDATE_FIELDS = {
        "_id",
        "id",
        "created_at",
        "created_by",
        "auto_approve_below",
    }

    OPTIONAL_TEXT_FIELDS = {
        "description",
        "created_by",
        "updated_by",
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.claim_types

    # -------------------------
    # Internal helpers
    # -------------------------

    def _normalize_code(self, code: str) -> str:
        """
        Normalize claim type code to uppercase.
        """
        return str(code).strip().upper()

    def _normalize_currency(self, currency: Optional[str]) -> str:
        """
        Normalize currency code.

        Repository only normalizes.
        Model/schema/service should validate business rules.
        """
        if not currency:
            return "INR"

        return str(currency).strip().upper()

    def _normalize_optional_text(self, value: Optional[str]) -> Optional[str]:
        """
        Strip optional text and convert empty string to None.
        """
        if value is None:
            return None

        value = str(value).strip()
        return value or None

    def _normalize_list_text(
        self,
        values: Optional[List[str]],
        default: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Normalize list of strings.

        Example:
        [".PDF", "jpg", " JPG "] -> ["pdf", "jpg"]

        If values is empty or invalid, returns default file types.
        """
        fallback = default or self.DEFAULT_ALLOWED_FILE_TYPES

        if not values:
            return list(fallback)

        cleaned: List[str] = []

        for value in values:
            if value is None:
                continue

            item = str(value).strip().lower().replace(".", "")

            if item and item not in cleaned:
                cleaned.append(item)

        return cleaned or list(fallback)

    def _to_object_id(self, value: str) -> Optional[ObjectId]:
        """
        Safely convert string ID to MongoDB ObjectId.
        """
        try:
            return ObjectId(str(value))
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
        converted_documents: List[Dict[str, Any]] = []

        for document in documents:
            converted = self._convert_id(document)
            if converted is not None:
                converted_documents.append(converted)

        return converted_documents

    def _clean_insert_data(self, claim_type_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize claim type data before insert.
        """
        cleaned = dict(claim_type_data)

        if "code" in cleaned and cleaned["code"] is not None:
            cleaned["code"] = self._normalize_code(cleaned["code"])

        cleaned["currency"] = self._normalize_currency(cleaned.get("currency"))

        for field in self.OPTIONAL_TEXT_FIELDS:
            if field in cleaned:
                cleaned[field] = self._normalize_optional_text(cleaned[field])

        cleaned["allowed_file_types"] = self._normalize_list_text(
            cleaned.get("allowed_file_types"),
            default=self.DEFAULT_ALLOWED_FILE_TYPES,
        )

        cleaned.setdefault("default_monthly_limit", None)
        cleaned.setdefault("max_claim_amount", None)
        cleaned.setdefault("min_claim_amount", None)

        cleaned.setdefault("requires_bill", True)
        cleaned.setdefault("bill_threshold", None)
        cleaned.setdefault("max_file_size_mb", 5)

        cleaned.setdefault("requires_approval", True)
        cleaned.setdefault("approval_threshold", None)
        cleaned.setdefault("finance_approval_threshold", None)
        # Legacy/reference field only. New claim types must not enable auto approval.
        cleaned["auto_approve_below"] = None

        cleaned.setdefault("reimbursement_percentage", 100)
        cleaned.setdefault("is_taxable", False)

        cleaned.setdefault("available_during_probation", True)
        cleaned.setdefault("display_order", 0)
        cleaned.setdefault("is_active", True)

        now = datetime.utcnow()
        cleaned["created_at"] = now
        cleaned["updated_at"] = now

        return cleaned

    def _clean_update_data(self, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove fields that should never be updated directly.
        Normalize code, currency, list fields, and optional text fields.
        """
        cleaned: Dict[str, Any] = {}

        for key, value in update_data.items():
            if key in self.BLOCKED_UPDATE_FIELDS:
                continue

            cleaned[key] = value

        if "code" in cleaned and cleaned["code"] is not None:
            cleaned["code"] = self._normalize_code(cleaned["code"])

        if "currency" in cleaned:
            cleaned["currency"] = self._normalize_currency(cleaned.get("currency"))

        for field in self.OPTIONAL_TEXT_FIELDS:
            if field in cleaned:
                cleaned[field] = self._normalize_optional_text(cleaned[field])

        if "allowed_file_types" in cleaned:
            cleaned["allowed_file_types"] = self._normalize_list_text(
                cleaned.get("allowed_file_types"),
                default=self.DEFAULT_ALLOWED_FILE_TYPES,
            )

        cleaned["updated_at"] = datetime.utcnow()

        return cleaned

    def _build_filter_query(
        self,
        is_active: Optional[bool] = None,
        requires_bill: Optional[bool] = None,
        requires_approval: Optional[bool] = None,
        is_taxable: Optional[bool] = None,
        currency: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build MongoDB query for list/count operations.
        """
        query: Dict[str, Any] = {}

        if is_active is not None:
            query["is_active"] = is_active

        if requires_bill is not None:
            query["requires_bill"] = requires_bill

        if requires_approval is not None:
            query["requires_approval"] = requires_approval

        if is_taxable is not None:
            query["is_taxable"] = is_taxable

        if currency:
            query["currency"] = self._normalize_currency(currency)

        if search:
            search_text = search.strip()

            if search_text:
                safe_search = re.escape(search_text)
                query["$or"] = [
                    {"name": {"$regex": safe_search, "$options": "i"}},
                    {"code": {"$regex": safe_search.upper(), "$options": "i"}},
                    {"description": {"$regex": safe_search, "$options": "i"}},
                ]

        return query

    # -------------------------
    # Create
    # -------------------------

    async def create(self, claim_type_data: Dict[str, Any]) -> str:
        """
        Create a new claim type.

        Returns:
            Created claim type _id as string.

        Raises:
            DuplicateKeyError if claim type code already exists.
        """
        cleaned_data = self._clean_insert_data(claim_type_data)

        try:
            result = await self.collection.insert_one(cleaned_data)
            return str(result.inserted_id)
        except DuplicateKeyError:
            raise

    # -------------------------
    # Find operations
    # -------------------------

    async def find_by_id(self, claim_type_id: str) -> Optional[Dict[str, Any]]:
        """
        Find claim type by MongoDB _id.
        """
        object_id = self._to_object_id(claim_type_id)

        if object_id is None:
            return None

        claim_type = await self.collection.find_one({"_id": object_id})
        return self._convert_id(claim_type)

    async def find_active_by_id(
        self,
        claim_type_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Find active claim type by MongoDB _id.
        """
        object_id = self._to_object_id(claim_type_id)

        if object_id is None:
            return None

        claim_type = await self.collection.find_one(
            {
                "_id": object_id,
                "is_active": True,
            }
        )

        return self._convert_id(claim_type)

    async def find_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Find claim type by unique code.
        """
        claim_type = await self.collection.find_one(
            {
                "code": self._normalize_code(code),
            }
        )

        return self._convert_id(claim_type)

    async def find_active_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Find active claim type by unique code.
        """
        claim_type = await self.collection.find_one(
            {
                "code": self._normalize_code(code),
                "is_active": True,
            }
        )

        return self._convert_id(claim_type)

    async def exists_by_id(self, claim_type_id: str) -> bool:
        """
        Check whether claim type exists by ID.
        """
        object_id = self._to_object_id(claim_type_id)

        if object_id is None:
            return False

        count = await self.collection.count_documents({"_id": object_id}, limit=1)
        return count > 0

    async def active_exists_by_id(self, claim_type_id: str) -> bool:
        """
        Check whether active claim type exists by ID.
        """
        object_id = self._to_object_id(claim_type_id)

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
        Check whether claim type code already exists.

        exclude_id is used during update so the same claim type can keep its code.
        """
        query: Dict[str, Any] = {
            "code": self._normalize_code(code),
        }

        if exclude_id:
            object_id = self._to_object_id(exclude_id)

            if object_id is None:
                return False

            query["_id"] = {"$ne": object_id}

        count = await self.collection.count_documents(query, limit=1)
        return count > 0

    # -------------------------
    # List and search
    # -------------------------

    async def list_all(
        self,
        is_active: Optional[bool] = None,
        requires_bill: Optional[bool] = None,
        requires_approval: Optional[bool] = None,
        is_taxable: Optional[bool] = None,
        currency: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "display_order",
        sort_order: str = "asc",
        skip: int = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List claim types with filtering, search, sorting, and pagination.
        """
        query = self._build_filter_query(
            is_active=is_active,
            requires_bill=requires_bill,
            requires_approval=requires_approval,
            is_taxable=is_taxable,
            currency=currency,
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

        claim_types = await cursor.to_list(length=safe_limit)
        return self._convert_many_ids(claim_types)

    async def list_active_for_dropdown(
        self,
        include_taxable: bool = True,
        currency: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List active claim types for frontend dropdowns.

        include_taxable:
        - True: show taxable and non-taxable claim types
        - False: show only non-taxable claim types
        """
        query: Dict[str, Any] = {
            "is_active": True,
        }

        if not include_taxable:
            query["is_taxable"] = False

        if currency:
            query["currency"] = self._normalize_currency(currency)

        cursor = self.collection.find(query).sort(
            [
                ("display_order", ASCENDING),
                ("name", ASCENDING),
            ]
        )

        claim_types = await cursor.to_list(length=500)
        return self._convert_many_ids(claim_types)


    async def count(
        self,
        is_active: Optional[bool] = None,
        requires_bill: Optional[bool] = None,
        requires_approval: Optional[bool] = None,
        is_taxable: Optional[bool] = None,
        currency: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        """
        Count claim types matching filters.

        Useful for pagination metadata.
        """
        query = self._build_filter_query(
            is_active=is_active,
            requires_bill=requires_bill,
            requires_approval=requires_approval,
            is_taxable=is_taxable,
            currency=currency,
            search=search,
        )

        return await self.collection.count_documents(query)

    # -------------------------
    # Update
    # -------------------------

    async def update(
        self,
        claim_type_id: str,
        update_data: Dict[str, Any],
    ) -> bool:
        """
        Update claim type fields.

        Returns:
            True if claim type exists and update operation matched it.
        """
        object_id = self._to_object_id(claim_type_id)

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
        Update display_order for multiple claim types.

        Expected item format:
        {
            "id": "claim_type_id",
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
            claim_type_id = item.get("id") or item.get("_id")
            display_order = item.get("display_order")

            if claim_type_id is None or display_order is None:
                errors.append(
                    {
                        "index": index,
                        "error": "id and display_order are required",
                    }
                )
                continue

            object_id = self._to_object_id(str(claim_type_id))

            if object_id is None:
                errors.append(
                    {
                        "index": index,
                        "id": claim_type_id,
                        "error": "Invalid claim type ID",
                    }
                )
                continue

            try:
                safe_display_order = max(int(display_order), 0)
            except (TypeError, ValueError):
                errors.append(
                    {
                        "index": index,
                        "id": claim_type_id,
                        "error": "display_order must be a valid integer",
                    }
                )
                continue

            update_data: Dict[str, Any] = {
                "display_order": safe_display_order,
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
                        "id": claim_type_id,
                        "error": "Claim type not found",
                    }
                )

        return updated_count, errors

    async def bulk_update_limits(
        self,
        updates: List[Dict[str, Any]],
        updated_by: Optional[str] = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """
        Bulk update limits for multiple claim types.

        Useful for yearly policy changes.

        Expected item format:
        {
            "id": "claim_type_id",
            "default_annual_limit": 50000,
            "default_monthly_limit": 5000,
            "max_claim_amount": 10000,
            "min_claim_amount": 100
        }

        Returns:
            Tuple of:
            - updated_count
            - errors
        """
        updated_count = 0
        errors: List[Dict[str, Any]] = []

        allowed_limit_fields = {
            "default_annual_limit",
            "default_monthly_limit",
            "max_claim_amount",
            "min_claim_amount",
            "approval_threshold",
            "finance_approval_threshold",
        }

        for index, item in enumerate(updates):
            claim_type_id = item.get("id") or item.get("_id")

            if not claim_type_id:
                errors.append(
                    {
                        "index": index,
                        "error": "id is required",
                    }
                )
                continue

            object_id = self._to_object_id(str(claim_type_id))

            if object_id is None:
                errors.append(
                    {
                        "index": index,
                        "id": claim_type_id,
                        "error": "Invalid claim type ID",
                    }
                )
                continue

            update_data = {
                key: value
                for key, value in item.items()
                if key in allowed_limit_fields and value is not None
            }

            if not update_data:
                errors.append(
                    {
                        "index": index,
                        "id": claim_type_id,
                        "error": "No limit fields provided",
                    }
                )
                continue

            update_data["updated_at"] = datetime.utcnow()

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
                        "id": claim_type_id,
                        "error": "Claim type not found",
                    }
                )

        return updated_count, errors

    # -------------------------
    # Activate / deactivate
    # -------------------------

    async def deactivate(
        self,
        claim_type_id: str,
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Soft delete claim type by setting is_active=False.

        The document remains in MongoDB.
        """
        object_id = self._to_object_id(claim_type_id)

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
        claim_type_id: str,
        updated_by: Optional[str] = None,
    ) -> bool:
        """
        Reactivate a deactivated claim type.
        """
        object_id = self._to_object_id(claim_type_id)

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
        claim_types: List[Dict[str, Any]],
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """
        Create multiple claim types.

        Returns:
            Tuple of:
            - created_ids
            - errors

        This keeps per-record error reporting, useful for bulk import UI.
        """
        created_ids: List[str] = []
        errors: List[Dict[str, Any]] = []

        for index, claim_type_data in enumerate(claim_types):
            try:
                created_id = await self.create(claim_type_data)
                created_ids.append(created_id)

            except DuplicateKeyError:
                errors.append(
                    {
                        "index": index,
                        "code": claim_type_data.get("code"),
                        "error": "Claim type code already exists",
                    }
                )

            except Exception as exc:
                errors.append(
                    {
                        "index": index,
                        "code": claim_type_data.get("code"),
                        "error": str(exc),
                    }
                )

        return created_ids, errors

    # -------------------------
    # Rule helpers
    # -------------------------

    async def get_claim_rules_by_id(
        self,
        claim_type_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get active claim type rules by ID.

        Used later by claim validation service before submitting claim.
        """
        claim_type = await self.find_active_by_id(claim_type_id)

        if not claim_type:
            return None

        return {
            "id": claim_type.get("id") or claim_type.get("_id"),
            "name": claim_type.get("name"),
            "code": claim_type.get("code"),
            "currency": claim_type.get("currency", "INR"),
            "default_annual_limit": claim_type.get("default_annual_limit", 0),
            "default_monthly_limit": claim_type.get("default_monthly_limit"),
            "max_claim_amount": claim_type.get("max_claim_amount"),
            "min_claim_amount": claim_type.get("min_claim_amount"),
            "requires_bill": claim_type.get("requires_bill", True),
            "bill_threshold": claim_type.get("bill_threshold"),
            "allowed_file_types": claim_type.get(
                "allowed_file_types",
                self.DEFAULT_ALLOWED_FILE_TYPES,
            ),
            "max_file_size_mb": claim_type.get("max_file_size_mb", 5),
            "requires_approval": claim_type.get("requires_approval", True),
            "approval_threshold": claim_type.get("approval_threshold"),
            "finance_approval_threshold": claim_type.get("finance_approval_threshold"),
            "auto_approve_below": None,  # legacy/reference only, never used for approval
            "reimbursement_percentage": claim_type.get("reimbursement_percentage", 100),
            "is_taxable": claim_type.get("is_taxable", False),
            "available_during_probation": claim_type.get(
                "available_during_probation",
                True,
            ),
        }

    async def get_claim_rules_by_code(
        self,
        code: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get active claim type rules by code.
        """
        claim_type = await self.find_active_by_code(code)

        if not claim_type:
            return None

        claim_type_id = claim_type.get("id") or claim_type.get("_id")
        return await self.get_claim_rules_by_id(claim_type_id)

    # -------------------------
    # Statistics
    # -------------------------

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get claim type statistics for admin dashboard.
        """
        total = await self.collection.count_documents({})
        active = await self.collection.count_documents({"is_active": True})
        inactive = total - active

        requires_bill = await self.collection.count_documents(
            {"is_active": True, "requires_bill": True}
        )

        no_bill_required = await self.collection.count_documents(
            {"is_active": True, "requires_bill": False}
        )

        requires_approval = await self.collection.count_documents(
            {"is_active": True, "requires_approval": True}
        )

        legacy_auto_approval_configured = await self.collection.count_documents(
            {
                "is_active": True,
                "auto_approve_below": {"$ne": None},
            }
        )

        finance_approval_enabled = await self.collection.count_documents(
            {
                "is_active": True,
                "finance_approval_threshold": {"$ne": None},
            }
        )

        taxable = await self.collection.count_documents(
            {"is_active": True, "is_taxable": True}
        )

        non_taxable = await self.collection.count_documents(
            {"is_active": True, "is_taxable": False}
        )

        probation_available = await self.collection.count_documents(
            {"is_active": True, "available_during_probation": True}
        )

        return {
            "total": total,
            "active": active,
            "inactive": inactive,
            "requires_bill": requires_bill,
            "no_bill_required": no_bill_required,
            "requires_approval": requires_approval,
            "legacy_auto_approval_configured": legacy_auto_approval_configured,
            "finance_approval_enabled": finance_approval_enabled,
            "taxable": taxable,
            "non_taxable": non_taxable,
            "probation_available": probation_available,
        }