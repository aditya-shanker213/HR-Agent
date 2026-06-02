"""
Claim repository for MongoDB operations.

Handles all database queries for the claims collection.

Pattern:
Route -> Service -> Repository -> MongoDB

Repository rules:
- No business logic here.
- No permission/RBAC logic here.
- No policy validation here.
- No LLM/AI decision logic here.
- Repository only builds MongoDB queries and updates.
- Service layer decides whether an action is allowed.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime as DateTime
from datetime import timedelta
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from backend.app.models.claim_model import (
    ClaimActionType,
    ClaimApprovalStatus,
    ClaimApproverRole,
    ClaimPaymentStatus,
    ClaimPriority,
    ClaimSource,
    ClaimStatus,
)


class ClaimRepository:
    """
    Repository for claims collection MongoDB operations.

    This repository supports:
    - Local MVP claims
    - HRMS/imported read-only claims
    - Employee claim history
    - Manager/finance/HR approval queues
    - Structured approval steps
    - Action history
    - Payment processing fields
    - Dashboard/statistics queries
    """

    READ_ONLY_UPDATE_BLOCKED_FIELDS = {
        "claim_id",
        "company_id",
        "source",
        "external_hrms_id",
        "is_read_only",
        "employee_id",
        "employee_code",
        "employee_name",
        "department_id",
        "department_name",
        "manager_id",
        "manager_name",
        "claim_type_id",
        "claim_type_code",
        "claim_type_name",
        "policy_snapshot",
        "created_at",
        "created_by",
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.claims

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _enum_value(self, value: Any) -> Any:
        """
        Convert enum to its string value for MongoDB query/update.
        """
        if hasattr(value, "value"):
            return value.value
        return value

    def _normalize_company_id(self, company_id: Optional[str] = "default") -> str:
        """
        Normalize company_id.
        """
        if not company_id:
            return "default"

        normalized = str(company_id).strip().lower()

        if not normalized:
            return "default"

        return normalized

    def _normalize_claim_id(self, claim_id: str) -> str:
        """
        Normalize claim_id.
        """
        return str(claim_id).strip().upper()

    def _to_object_id(self, value: str) -> Optional[ObjectId]:
        """
        Convert string to ObjectId safely.
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
        Convert MongoDB _id to string and add id field.
        """
        if document and "_id" in document:
            document["_id"] = str(document["_id"])
            document["id"] = document["_id"]

        return document

    def _convert_many(
        self,
        documents: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Convert _id for multiple MongoDB documents.
        """
        return [self._convert_id(doc) for doc in documents if doc is not None]

    def _clean_insert_data(self, claim_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize insert data before MongoDB insert.
        """
        cleaned = dict(claim_data)

        cleaned["company_id"] = self._normalize_company_id(
            cleaned.get("company_id", "default")
        )

        if "claim_id" in cleaned:
            cleaned["claim_id"] = self._normalize_claim_id(cleaned["claim_id"])

        now = DateTime.utcnow()
        cleaned.setdefault("created_at", now)
        cleaned.setdefault("updated_at", now)

        return cleaned

    def _clean_update_data(
        self,
        update_data: Dict[str, Any],
        allow_protected_fields: bool = False,
    ) -> Dict[str, Any]:
        """
        Normalize update payload.

        Protected fields are blocked by default because they should not be
        changed casually after claim creation.
        """
        cleaned: Dict[str, Any] = {}

        for key, value in update_data.items():
            if not allow_protected_fields and key in self.READ_ONLY_UPDATE_BLOCKED_FIELDS:
                continue

            cleaned[key] = self._enum_value(value)

        cleaned["updated_at"] = DateTime.utcnow()
        return cleaned

    def _editable_filter(
        self,
        base_query: Dict[str, Any],
        prevent_read_only_update: bool = True,
    ) -> Dict[str, Any]:
        """
        Add read-only protection to update filter.

        HRMS-owned records should not be locally editable unless the service
        explicitly calls a sync/import method.
        """
        query = dict(base_query)

        if prevent_read_only_update:
            query["is_read_only"] = {"$ne": True}

        return query

    def _build_date_range_filter(
        self,
        from_date: Optional[Date] = None,
        to_date: Optional[Date] = None,
        field_name: str = "expense_date",
    ) -> Dict[str, Any]:
        """
        Build MongoDB date range filter.
        """
        if not from_date and not to_date:
            return {}

        date_query: Dict[str, Any] = {}

        if from_date:
            date_query["$gte"] = from_date

        if to_date:
            date_query["$lte"] = to_date

        return {field_name: date_query}

    def _build_sort(self, sort_by: str = "created_at", sort_order: str = "desc"):
        """
        Build safe MongoDB sort tuple.
        """
        allowed_sort_fields = {
            "created_at",
            "updated_at",
            "expense_date",
            "amount",
            "approved_amount",
            "paid_amount",
            "status",
            "priority",
        }

        if sort_by not in allowed_sort_fields:
            sort_by = "created_at"

        direction = ASCENDING if sort_order == "asc" else DESCENDING
        return [(sort_by, direction)]

    def _build_list_query(
        self,
        company_id: str = "default",
        status: Optional[ClaimStatus] = None,
        source: Optional[ClaimSource] = None,
        claim_type_id: Optional[str] = None,
        claim_type_code: Optional[str] = None,
        employee_id: Optional[str] = None,
        employee_code: Optional[str] = None,
        department_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        priority: Optional[ClaimPriority] = None,
        payment_status: Optional[ClaimPaymentStatus] = None,
        is_read_only: Optional[bool] = None,
        from_date: Optional[Date] = None,
        to_date: Optional[Date] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build list/search query.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
        }

        if status:
            query["status"] = self._enum_value(status)

        if source:
            query["source"] = self._enum_value(source)

        if claim_type_id:
            query["claim_type_id"] = claim_type_id

        if claim_type_code:
            query["claim_type_code"] = str(claim_type_code).strip().upper()

        if employee_id:
            query["employee_id"] = employee_id

        if employee_code:
            query["employee_code"] = employee_code

        if department_id:
            query["department_id"] = department_id

        if manager_id:
            query["manager_id"] = manager_id

        if priority:
            query["priority"] = self._enum_value(priority)

        if payment_status:
            query["payment_status"] = self._enum_value(payment_status)

        if is_read_only is not None:
            query["is_read_only"] = is_read_only

        query.update(
            self._build_date_range_filter(
                from_date=from_date,
                to_date=to_date,
                field_name="expense_date",
            )
        )

        if min_amount is not None or max_amount is not None:
            amount_filter: Dict[str, Any] = {}

            if min_amount is not None:
                amount_filter["$gte"] = min_amount

            if max_amount is not None:
                amount_filter["$lte"] = max_amount

            query["amount"] = amount_filter

        if search:
            search_text = str(search).strip()

            if search_text:
                query["$or"] = [
                    {"claim_id": {"$regex": search_text, "$options": "i"}},
                    {"title": {"$regex": search_text, "$options": "i"}},
                    {"description": {"$regex": search_text, "$options": "i"}},
                    {"employee_name": {"$regex": search_text, "$options": "i"}},
                    {"employee_code": {"$regex": search_text, "$options": "i"}},
                    {"claim_type_name": {"$regex": search_text, "$options": "i"}},
                    {"claim_type_code": {"$regex": search_text, "$options": "i"}},
                    {"vendor_name": {"$regex": search_text, "$options": "i"}},
                    {"bill_number": {"$regex": search_text, "$options": "i"}},
                ]

        return query

    # ---------------------------------------------------------------------
    # Create operations
    # ---------------------------------------------------------------------

    async def create(self, claim_data: Dict[str, Any]) -> str:
        """
        Create a new claim.

        Returns:
            claim_id
        """
        cleaned_data = self._clean_insert_data(claim_data)
        await self.collection.insert_one(cleaned_data)
        return cleaned_data["claim_id"]

    async def bulk_create(self, claims_data: List[Dict[str, Any]]) -> int:
        """
        Insert multiple claims.

        Useful for HRMS/import sync.
        """
        if not claims_data:
            return 0

        cleaned = [self._clean_insert_data(item) for item in claims_data]
        result = await self.collection.insert_many(cleaned)
        return len(result.inserted_ids)

    # ---------------------------------------------------------------------
    # Basic read operations
    # ---------------------------------------------------------------------

    async def find_by_claim_id(
        self,
        claim_id: str,
        company_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find claim by claim_id.
        """
        query: Dict[str, Any] = {
            "claim_id": self._normalize_claim_id(claim_id),
        }

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        document = await self.collection.find_one(query)
        return self._convert_id(document)

    async def find_by_id(self, claim_id: str) -> Optional[Dict[str, Any]]:
        """
        Backward-compatible alias.

        In this project claim_id means business claim ID, not MongoDB _id.
        """
        return await self.find_by_claim_id(claim_id)

    async def find_by_mongo_id(self, mongo_id: str) -> Optional[Dict[str, Any]]:
        """
        Find claim by MongoDB _id.
        """
        object_id = self._to_object_id(mongo_id)

        if object_id is None:
            return None

        document = await self.collection.find_one({"_id": object_id})
        return self._convert_id(document)

    async def find_by_external_hrms_id(
        self,
        external_hrms_id: str,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Find claim by external HRMS ID.
        """
        document = await self.collection.find_one(
            {
                "company_id": self._normalize_company_id(company_id),
                "external_hrms_id": str(external_hrms_id).strip(),
            }
        )

        return self._convert_id(document)

    async def claim_id_exists(
        self,
        claim_id: str,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Check if claim_id exists.
        """
        query: Dict[str, Any] = {
            "claim_id": self._normalize_claim_id(claim_id),
        }

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        count = await self.collection.count_documents(query, limit=1)
        return count > 0

    async def external_hrms_id_exists(
        self,
        external_hrms_id: str,
        company_id: str = "default",
    ) -> bool:
        """
        Check whether an external HRMS claim ID already exists.
        """
        count = await self.collection.count_documents(
            {
                "company_id": self._normalize_company_id(company_id),
                "external_hrms_id": str(external_hrms_id).strip(),
            },
            limit=1,
        )

        return count > 0

    # ---------------------------------------------------------------------
    # List/search operations
    # ---------------------------------------------------------------------

    async def list_claims(
        self,
        company_id: str = "default",
        status: Optional[ClaimStatus] = None,
        source: Optional[ClaimSource] = None,
        claim_type_id: Optional[str] = None,
        claim_type_code: Optional[str] = None,
        employee_id: Optional[str] = None,
        employee_code: Optional[str] = None,
        department_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        priority: Optional[ClaimPriority] = None,
        payment_status: Optional[ClaimPaymentStatus] = None,
        is_read_only: Optional[bool] = None,
        from_date: Optional[Date] = None,
        to_date: Optional[Date] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> List[Dict[str, Any]]:
        """
        List claims with filters.
        """
        query = self._build_list_query(
            company_id=company_id,
            status=status,
            source=source,
            claim_type_id=claim_type_id,
            claim_type_code=claim_type_code,
            employee_id=employee_id,
            employee_code=employee_code,
            department_id=department_id,
            manager_id=manager_id,
            priority=priority,
            payment_status=payment_status,
            is_read_only=is_read_only,
            from_date=from_date,
            to_date=to_date,
            min_amount=min_amount,
            max_amount=max_amount,
            search=search,
        )

        cursor = (
            self.collection.find(query)
            .sort(self._build_sort(sort_by, sort_order))
            .skip(skip)
            .limit(limit)
        )

        documents = await cursor.to_list(length=limit)
        return self._convert_many(documents)

    async def count_claims(
        self,
        company_id: str = "default",
        status: Optional[ClaimStatus] = None,
        source: Optional[ClaimSource] = None,
        claim_type_id: Optional[str] = None,
        claim_type_code: Optional[str] = None,
        employee_id: Optional[str] = None,
        employee_code: Optional[str] = None,
        department_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        priority: Optional[ClaimPriority] = None,
        payment_status: Optional[ClaimPaymentStatus] = None,
        is_read_only: Optional[bool] = None,
        from_date: Optional[Date] = None,
        to_date: Optional[Date] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        search: Optional[str] = None,
    ) -> int:
        """
        Count claims with filters.
        """
        query = self._build_list_query(
            company_id=company_id,
            status=status,
            source=source,
            claim_type_id=claim_type_id,
            claim_type_code=claim_type_code,
            employee_id=employee_id,
            employee_code=employee_code,
            department_id=department_id,
            manager_id=manager_id,
            priority=priority,
            payment_status=payment_status,
            is_read_only=is_read_only,
            from_date=from_date,
            to_date=to_date,
            min_amount=min_amount,
            max_amount=max_amount,
            search=search,
        )

        return await self.collection.count_documents(query)

    async def find_by_employee(
        self,
        employee_id: str,
        company_id: str = "default",
        status: Optional[ClaimStatus] = None,
        claim_type_id: Optional[str] = None,
        from_date: Optional[Date] = None,
        to_date: Optional[Date] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Find claims by employee.
        """
        return await self.list_claims(
            company_id=company_id,
            employee_id=employee_id,
            status=status,
            claim_type_id=claim_type_id,
            from_date=from_date,
            to_date=to_date,
            skip=skip,
            limit=limit,
            sort_by="created_at",
            sort_order="desc",
        )

    async def count_by_employee(
        self,
        employee_id: str,
        company_id: str = "default",
        status: Optional[ClaimStatus] = None,
        claim_type_id: Optional[str] = None,
        from_date: Optional[Date] = None,
        to_date: Optional[Date] = None,
    ) -> int:
        """
        Count claims by employee.
        """
        return await self.count_claims(
            company_id=company_id,
            employee_id=employee_id,
            status=status,
            claim_type_id=claim_type_id,
            from_date=from_date,
            to_date=to_date,
        )

    async def search_claims(
        self,
        search_text: str,
        company_id: str = "default",
        employee_id: Optional[str] = None,
        status: Optional[ClaimStatus] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Search claims by claim_id/title/description/employee/claim type/vendor.
        """
        return await self.list_claims(
            company_id=company_id,
            employee_id=employee_id,
            status=status,
            search=search_text,
            skip=skip,
            limit=limit,
            sort_by="created_at",
            sort_order="desc",
        )

    # ---------------------------------------------------------------------
    # Pending approval operations
    # ---------------------------------------------------------------------

    async def find_pending_approvals(
        self,
        company_id: str = "default",
        approver_role: Optional[ClaimApproverRole] = None,
        approver_id: Optional[str] = None,
        claim_type_id: Optional[str] = None,
        department_id: Optional[str] = None,
        priority: Optional[ClaimPriority] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Find claims waiting for approval.

        Uses structured approval_steps.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
            "status": {
                "$in": [
                    ClaimStatus.PENDING.value,
                    ClaimStatus.RESUBMITTED.value,
                    ClaimStatus.MANAGER_APPROVED.value,
                    ClaimStatus.FINANCE_APPROVED.value,
                ]
            },
            "approval_steps": {
                "$elemMatch": {
                    "approval_status": ClaimApprovalStatus.PENDING.value,
                }
            },
        }

        if approver_role:
            query["approval_steps"]["$elemMatch"]["approver_role"] = self._enum_value(
                approver_role
            )

        if approver_id:
            query["approval_steps"]["$elemMatch"]["approver_id"] = approver_id

        if claim_type_id:
            query["claim_type_id"] = claim_type_id

        if department_id:
            query["department_id"] = department_id

        if priority:
            query["priority"] = self._enum_value(priority)

        if min_amount is not None or max_amount is not None:
            amount_filter: Dict[str, Any] = {}

            if min_amount is not None:
                amount_filter["$gte"] = min_amount

            if max_amount is not None:
                amount_filter["$lte"] = max_amount

            query["amount"] = amount_filter

        cursor = (
            self.collection.find(query)
            .sort([("priority", DESCENDING), ("created_at", ASCENDING)])
            .skip(skip)
            .limit(limit)
        )

        documents = await cursor.to_list(length=limit)
        return self._convert_many(documents)

    async def count_pending_approvals(
        self,
        company_id: str = "default",
        approver_role: Optional[ClaimApproverRole] = None,
        approver_id: Optional[str] = None,
        claim_type_id: Optional[str] = None,
        department_id: Optional[str] = None,
        priority: Optional[ClaimPriority] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
    ) -> int:
        """
        Count claims waiting for approval.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
            "status": {
                "$in": [
                    ClaimStatus.PENDING.value,
                    ClaimStatus.RESUBMITTED.value,
                    ClaimStatus.MANAGER_APPROVED.value,
                    ClaimStatus.FINANCE_APPROVED.value,
                ]
            },
            "approval_steps": {
                "$elemMatch": {
                    "approval_status": ClaimApprovalStatus.PENDING.value,
                }
            },
        }

        if approver_role:
            query["approval_steps"]["$elemMatch"]["approver_role"] = self._enum_value(
                approver_role
            )

        if approver_id:
            query["approval_steps"]["$elemMatch"]["approver_id"] = approver_id

        if claim_type_id:
            query["claim_type_id"] = claim_type_id

        if department_id:
            query["department_id"] = department_id

        if priority:
            query["priority"] = self._enum_value(priority)

        if min_amount is not None or max_amount is not None:
            amount_filter: Dict[str, Any] = {}

            if min_amount is not None:
                amount_filter["$gte"] = min_amount

            if max_amount is not None:
                amount_filter["$lte"] = max_amount

            query["amount"] = amount_filter

        return await self.collection.count_documents(query)

    # ---------------------------------------------------------------------
    # Duplicate detection / limit helper queries
    # ---------------------------------------------------------------------

    async def find_recent_similar_claim(
        self,
        employee_id: str,
        claim_type_id: str,
        amount: float,
        expense_date: Date,
        company_id: str = "default",
        within_hours: int = 48,
        exclude_claim_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find recent similar claim for duplicate detection.

        Duplicate detection is a helper query only.
        Service decides what to do with this result.
        """
        time_threshold = DateTime.utcnow() - timedelta(hours=within_hours)

        amount_min = amount * 0.95
        amount_max = amount * 1.05

        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
            "employee_id": employee_id,
            "claim_type_id": claim_type_id,
            "amount": {"$gte": amount_min, "$lte": amount_max},
            "expense_date": expense_date,
            "created_at": {"$gte": time_threshold},
            "status": {
                "$nin": [
                    ClaimStatus.REJECTED.value,
                    ClaimStatus.CANCELLED.value,
                    ClaimStatus.WITHDRAWN.value,
                    ClaimStatus.FAILED.value,
                ]
            },
        }

        if exclude_claim_id:
            query["claim_id"] = {"$ne": self._normalize_claim_id(exclude_claim_id)}

        document = await self.collection.find_one(query)
        return self._convert_id(document)

    async def get_total_claimed_by_type(
        self,
        employee_id: str,
        claim_type_id: str,
        company_id: str = "default",
        year: Optional[int] = None,
        month: Optional[int] = None,
        include_statuses: Optional[List[ClaimStatus]] = None,
    ) -> float:
        """
        Get total claim amount for employee + claim type.

        Used by service for monthly/yearly limits.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
            "employee_id": employee_id,
            "claim_type_id": claim_type_id,
            "status": {
                "$nin": [
                    ClaimStatus.REJECTED.value,
                    ClaimStatus.CANCELLED.value,
                    ClaimStatus.WITHDRAWN.value,
                    ClaimStatus.FAILED.value,
                ]
            },
        }

        if include_statuses:
            query["status"] = {"$in": [status.value for status in include_statuses]}

        if year:
            start_date = Date(year, month or 1, 1)

            if month:
                if month == 12:
                    end_date = Date(year + 1, 1, 1)
                else:
                    end_date = Date(year, month + 1, 1)
            else:
                end_date = Date(year + 1, 1, 1)

            query["expense_date"] = {
                "$gte": start_date,
                "$lt": end_date,
            }

        pipeline = [
            {"$match": query},
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": "$amount"},
                }
            },
        ]

        result = await self.collection.aggregate(pipeline).to_list(length=1)
        return float(result[0]["total"]) if result else 0.0

    # ---------------------------------------------------------------------
    # Generic update operations
    # ---------------------------------------------------------------------

    async def update(
        self,
        claim_id: str,
        update_data: Dict[str, Any],
        company_id: Optional[str] = None,
        prevent_read_only_update: bool = True,
        allow_protected_fields: bool = False,
    ) -> bool:
        """
        Update claim fields.

        By default, read-only HRMS records cannot be updated.
        """
        base_query: Dict[str, Any] = {
            "claim_id": self._normalize_claim_id(claim_id),
        }

        if company_id is not None:
            base_query["company_id"] = self._normalize_company_id(company_id)

        query = self._editable_filter(
            base_query,
            prevent_read_only_update=prevent_read_only_update,
        )

        safe_update = self._clean_update_data(
            update_data,
            allow_protected_fields=allow_protected_fields,
        )

        result = await self.collection.update_one(
            query,
            {"$set": safe_update},
        )

        return result.matched_count > 0

    async def update_status(
        self,
        claim_id: str,
        new_status: ClaimStatus,
        company_id: Optional[str] = None,
        extra_updates: Optional[Dict[str, Any]] = None,
        prevent_read_only_update: bool = True,
    ) -> bool:
        """
        Generic status update helper.

        Service layer should prepare all status-specific fields.
        """
        update_data: Dict[str, Any] = {
            "status": new_status.value,
        }

        if extra_updates:
            update_data.update(extra_updates)

        return await self.update(
            claim_id=claim_id,
            company_id=company_id,
            update_data=update_data,
            prevent_read_only_update=prevent_read_only_update,
        )

    async def replace_from_hrms_sync(
        self,
        claim_id: str,
        update_data: Dict[str, Any],
        company_id: str = "default",
    ) -> bool:
        """
        Update HRMS/imported read-only claim during trusted sync.

        This bypasses normal read-only protection and should only be called
        by HRMS sync service, not normal routes.
        """
        return await self.update(
            claim_id=claim_id,
            company_id=company_id,
            update_data=update_data,
            prevent_read_only_update=False,
            allow_protected_fields=True,
        )

    # ---------------------------------------------------------------------
    # Action history operations
    # ---------------------------------------------------------------------

    async def add_action_history(
        self,
        claim_id: str,
        action_event: Dict[str, Any],
        company_id: Optional[str] = None,
        prevent_read_only_update: bool = True,
    ) -> bool:
        """
        Append one action history event.
        """
        base_query: Dict[str, Any] = {
            "claim_id": self._normalize_claim_id(claim_id),
        }

        if company_id is not None:
            base_query["company_id"] = self._normalize_company_id(company_id)

        query = self._editable_filter(
            base_query,
            prevent_read_only_update=prevent_read_only_update,
        )

        action_event = dict(action_event)
        action_event.setdefault("action_at", DateTime.utcnow())

        if "action" in action_event:
            action_event["action"] = self._enum_value(action_event["action"])

        if "old_status" in action_event:
            action_event["old_status"] = self._enum_value(action_event["old_status"])

        if "new_status" in action_event:
            action_event["new_status"] = self._enum_value(action_event["new_status"])

        result = await self.collection.update_one(
            query,
            {
                "$push": {"action_history": action_event},
                "$set": {"updated_at": DateTime.utcnow()},
            },
        )

        return result.matched_count > 0

    # ---------------------------------------------------------------------
    # Attachment operations
    # ---------------------------------------------------------------------

    async def add_attachment(
        self,
        claim_id: str,
        attachment: Dict[str, Any],
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Add attachment metadata to claim.
        """
        base_query: Dict[str, Any] = {
            "claim_id": self._normalize_claim_id(claim_id),
        }

        if company_id is not None:
            base_query["company_id"] = self._normalize_company_id(company_id)

        query = self._editable_filter(base_query)

        attachment = dict(attachment)
        attachment.setdefault("uploaded_at", DateTime.utcnow())

        result = await self.collection.update_one(
            query,
            {
                "$push": {"attachments": attachment},
                "$set": {"updated_at": DateTime.utcnow()},
            },
        )

        return result.matched_count > 0

    async def verify_attachment(
        self,
        claim_id: str,
        attachment_index: int,
        verified_by: str,
        is_verified: bool = True,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Verify or unverify attachment by list index.
        """
        base_query: Dict[str, Any] = {
            "claim_id": self._normalize_claim_id(claim_id),
            f"attachments.{attachment_index}": {"$exists": True},
        }

        if company_id is not None:
            base_query["company_id"] = self._normalize_company_id(company_id)

        query = self._editable_filter(base_query)

        update_data: Dict[str, Any] = {
            f"attachments.{attachment_index}.is_verified": is_verified,
            "updated_at": DateTime.utcnow(),
        }

        if is_verified:
            update_data[f"attachments.{attachment_index}.verified_by"] = verified_by
            update_data[f"attachments.{attachment_index}.verified_at"] = DateTime.utcnow()
        else:
            update_data[f"attachments.{attachment_index}.verified_by"] = None
            update_data[f"attachments.{attachment_index}.verified_at"] = None

        result = await self.collection.update_one(
            query,
            {"$set": update_data},
        )

        return result.matched_count > 0

    async def remove_attachment(
        self,
        claim_id: str,
        file_url: str,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Remove attachment by file_url.
        """
        base_query: Dict[str, Any] = {
            "claim_id": self._normalize_claim_id(claim_id),
        }

        if company_id is not None:
            base_query["company_id"] = self._normalize_company_id(company_id)

        query = self._editable_filter(base_query)

        result = await self.collection.update_one(
            query,
            {
                "$pull": {"attachments": {"file_url": file_url}},
                "$set": {"updated_at": DateTime.utcnow()},
            },
        )

        return result.matched_count > 0

    # ---------------------------------------------------------------------
    # Approval workflow operations
    # ---------------------------------------------------------------------

    async def set_approval_steps(
        self,
        claim_id: str,
        approval_steps: List[Dict[str, Any]],
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Replace approval_steps.
        """
        return await self.update(
            claim_id=claim_id,
            company_id=company_id,
            update_data={"approval_steps": approval_steps},
        )

    async def update_approval_step(
        self,
        claim_id: str,
        step_order: int,
        step_update: Dict[str, Any],
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Update one approval step by step_order.
        """
        query: Dict[str, Any] = {
            "claim_id": self._normalize_claim_id(claim_id),
            "approval_steps.step_order": step_order,
        }

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        query = self._editable_filter(query)

        safe_update: Dict[str, Any] = {}

        for key, value in step_update.items():
            safe_update[f"approval_steps.$.{key}"] = self._enum_value(value)

        safe_update["updated_at"] = DateTime.utcnow()

        result = await self.collection.update_one(
            query,
            {"$set": safe_update},
        )

        return result.matched_count > 0

    async def approve_step(
        self,
        claim_id: str,
        step_order: int,
        approver_id: str,
        approver_name: Optional[str] = None,
        comments: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Mark one approval step as approved.
        """
        step_update = {
            "approver_id": approver_id,
            "approver_name": approver_name,
            "approval_status": ClaimApprovalStatus.APPROVED.value,
            "action_date": DateTime.utcnow(),
            "comments": comments,
        }

        return await self.update_approval_step(
            claim_id=claim_id,
            step_order=step_order,
            step_update=step_update,
            company_id=company_id,
        )

    async def reject_step(
        self,
        claim_id: str,
        step_order: int,
        approver_id: str,
        approver_name: Optional[str],
        rejection_reason: str,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Mark one approval step as rejected.
        """
        step_update = {
            "approver_id": approver_id,
            "approver_name": approver_name,
            "approval_status": ClaimApprovalStatus.REJECTED.value,
            "action_date": DateTime.utcnow(),
            "rejection_reason": rejection_reason,
        }

        return await self.update_approval_step(
            claim_id=claim_id,
            step_order=step_order,
            step_update=step_update,
            company_id=company_id,
        )

    async def send_back_step(
        self,
        claim_id: str,
        step_order: int,
        approver_id: str,
        approver_name: Optional[str],
        sent_back_reason: str,
        comments: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Mark one approval step as sent_back.
        """
        step_update = {
            "approver_id": approver_id,
            "approver_name": approver_name,
            "approval_status": ClaimApprovalStatus.SENT_BACK.value,
            "action_date": DateTime.utcnow(),
            "sent_back_reason": sent_back_reason,
            "comments": comments,
        }

        return await self.update_approval_step(
            claim_id=claim_id,
            step_order=step_order,
            step_update=step_update,
            company_id=company_id,
        )

    async def skip_step(
        self,
        claim_id: str,
        step_order: int,
        actor_id: str,
        reason: str,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Mark one approval step as skipped.
        """
        step_update = {
            "approver_id": actor_id,
            "approval_status": ClaimApprovalStatus.SKIPPED.value,
            "action_date": DateTime.utcnow(),
            "comments": reason,
        }

        return await self.update_approval_step(
            claim_id=claim_id,
            step_order=step_order,
            step_update=step_update,
            company_id=company_id,
        )

    # ---------------------------------------------------------------------
    # Lifecycle shortcut operations
    # ---------------------------------------------------------------------

    async def submit_claim(
        self,
        claim_id: str,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Mark claim as submitted/pending.
        """
        return await self.update_status(
            claim_id=claim_id,
            company_id=company_id,
            new_status=ClaimStatus.PENDING,
            extra_updates={
                "submitted_at": DateTime.utcnow(),
            },
        )

    async def resubmit_claim(
        self,
        claim_id: str,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Mark claim as resubmitted.
        """
        return await self.update_status(
            claim_id=claim_id,
            company_id=company_id,
            new_status=ClaimStatus.RESUBMITTED,
            extra_updates={
                "resubmitted_at": DateTime.utcnow(),
            },
        )

    async def approve_claim_final(
        self,
        claim_id: str,
        approved_by: str,
        approved_amount: float,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Mark claim as finally approved.
        """
        return await self.update_status(
            claim_id=claim_id,
            company_id=company_id,
            new_status=ClaimStatus.APPROVED,
            extra_updates={
                "approved_by": approved_by,
                "approved_amount": approved_amount,
                "approved_at": DateTime.utcnow(),
            },
        )

    async def reject_claim(
        self,
        claim_id: str,
        rejected_by: str,
        rejection_reason: str,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Reject claim.
        """
        return await self.update_status(
            claim_id=claim_id,
            company_id=company_id,
            new_status=ClaimStatus.REJECTED,
            extra_updates={
                "rejected_by": rejected_by,
                "rejection_reason": rejection_reason,
                "rejected_at": DateTime.utcnow(),
            },
        )

    async def send_back_claim(
        self,
        claim_id: str,
        sent_back_reason: str,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Send claim back to employee for correction.
        """
        return await self.update_status(
            claim_id=claim_id,
            company_id=company_id,
            new_status=ClaimStatus.SENT_BACK,
            extra_updates={
                "sent_back_reason": sent_back_reason,
                "sent_back_at": DateTime.utcnow(),
            },
        )

    async def cancel_claim(
        self,
        claim_id: str,
        cancellation_reason: str,
        cancelled_by: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Cancel claim.
        """
        return await self.update_status(
            claim_id=claim_id,
            company_id=company_id,
            new_status=ClaimStatus.CANCELLED,
            extra_updates={
                "cancelled_by": cancelled_by,
                "cancellation_reason": cancellation_reason,
                "cancelled_at": DateTime.utcnow(),
            },
        )

    async def withdraw_claim(
        self,
        claim_id: str,
        withdrawal_reason: str,
        withdrawn_by: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Withdraw claim.
        """
        return await self.update_status(
            claim_id=claim_id,
            company_id=company_id,
            new_status=ClaimStatus.WITHDRAWN,
            extra_updates={
                "withdrawn_by": withdrawn_by,
                "withdrawal_reason": withdrawal_reason,
                "withdrawn_at": DateTime.utcnow(),
            },
        )

    # ---------------------------------------------------------------------
    # Payment operations
    # ---------------------------------------------------------------------

    async def start_payment_processing(
        self,
        claim_id: str,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Mark claim payment as processing.
        """
        return await self.update_status(
            claim_id=claim_id,
            company_id=company_id,
            new_status=ClaimStatus.PROCESSING,
            extra_updates={
                "payment_status": ClaimPaymentStatus.PROCESSING.value,
            },
        )

    async def mark_paid(
        self,
        claim_id: str,
        payment_reference: str,
        payment_date: Date,
        paid_amount: float,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Mark claim as paid.
        """
        return await self.update_status(
            claim_id=claim_id,
            company_id=company_id,
            new_status=ClaimStatus.PAID,
            extra_updates={
                "payment_status": ClaimPaymentStatus.PAID.value,
                "payment_reference": payment_reference,
                "payment_date": payment_date,
                "paid_amount": paid_amount,
            },
        )

    async def mark_payment_failed(
        self,
        claim_id: str,
        payment_failure_reason: str,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Mark claim payment as failed.
        """
        return await self.update_status(
            claim_id=claim_id,
            company_id=company_id,
            new_status=ClaimStatus.FAILED,
            extra_updates={
                "payment_status": ClaimPaymentStatus.FAILED.value,
                "payment_failure_reason": payment_failure_reason,
            },
        )

    # ---------------------------------------------------------------------
    # Statistics / aggregation operations
    # ---------------------------------------------------------------------

    async def get_employee_statistics(
        self,
        employee_id: str,
        company_id: str = "default",
        year: Optional[int] = None,
        month: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get claim statistics for an employee.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
            "employee_id": employee_id,
        }

        if year:
            start_date = Date(year, month or 1, 1)

            if month:
                if month == 12:
                    end_date = Date(year + 1, 1, 1)
                else:
                    end_date = Date(year, month + 1, 1)
            else:
                end_date = Date(year + 1, 1, 1)

            query["expense_date"] = {
                "$gte": start_date,
                "$lt": end_date,
            }

        pipeline = [
            {"$match": query},
            {
                "$group": {
                    "_id": "$status",
                    "count": {"$sum": 1},
                    "claimed_amount": {"$sum": "$amount"},
                    "approved_amount": {"$sum": {"$ifNull": ["$approved_amount", 0]}},
                    "paid_amount": {"$sum": {"$ifNull": ["$paid_amount", 0]}},
                }
            },
        ]

        results = await self.collection.aggregate(pipeline).to_list(length=None)

        stats: Dict[str, Any] = {
            "total_claims": 0,
            "draft_claims": 0,
            "pending_claims": 0,
            "manager_approved_claims": 0,
            "finance_approved_claims": 0,
            "approved_claims": 0,
            "rejected_claims": 0,
            "cancelled_claims": 0,
            "withdrawn_claims": 0,
            "sent_back_claims": 0,
            "processing_claims": 0,
            "paid_claims": 0,
            "failed_claims": 0,
            "total_amount_claimed": 0.0,
            "total_amount_approved": 0.0,
            "total_amount_paid": 0.0,
            "pending_amount": 0.0,
            "rejected_amount": 0.0,
        }

        status_key_map = {
            ClaimStatus.DRAFT.value: "draft_claims",
            ClaimStatus.PENDING.value: "pending_claims",
            ClaimStatus.RESUBMITTED.value: "pending_claims",
            ClaimStatus.MANAGER_APPROVED.value: "manager_approved_claims",
            ClaimStatus.FINANCE_APPROVED.value: "finance_approved_claims",
            ClaimStatus.APPROVED.value: "approved_claims",
            ClaimStatus.REJECTED.value: "rejected_claims",
            ClaimStatus.CANCELLED.value: "cancelled_claims",
            ClaimStatus.WITHDRAWN.value: "withdrawn_claims",
            ClaimStatus.SENT_BACK.value: "sent_back_claims",
            ClaimStatus.PROCESSING.value: "processing_claims",
            ClaimStatus.PAID.value: "paid_claims",
            ClaimStatus.FAILED.value: "failed_claims",
        }

        pending_statuses = {
            ClaimStatus.PENDING.value,
            ClaimStatus.RESUBMITTED.value,
            ClaimStatus.MANAGER_APPROVED.value,
            ClaimStatus.FINANCE_APPROVED.value,
        }

        for result in results:
            status_value = result["_id"]
            count = int(result.get("count", 0))
            claimed_amount = float(result.get("claimed_amount", 0.0))
            approved_amount = float(result.get("approved_amount", 0.0))
            paid_amount = float(result.get("paid_amount", 0.0))

            stats["total_claims"] += count
            stats["total_amount_claimed"] += claimed_amount
            stats["total_amount_approved"] += approved_amount
            stats["total_amount_paid"] += paid_amount

            key = status_key_map.get(status_value)
            if key:
                stats[key] += count

            if status_value in pending_statuses:
                stats["pending_amount"] += claimed_amount

            if status_value == ClaimStatus.REJECTED.value:
                stats["rejected_amount"] += claimed_amount

        stats["claim_type_breakdown"] = await self.get_claim_type_breakdown(
            employee_id=employee_id,
            company_id=company_id,
            year=year,
        )

        stats["status_breakdown"] = {
            result["_id"]: int(result.get("count", 0)) for result in results
        }

        return stats

    async def get_claim_type_breakdown(
        self,
        employee_id: Optional[str] = None,
        company_id: str = "default",
        year: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Get claim count breakdown by claim type code/name.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
        }

        if employee_id:
            query["employee_id"] = employee_id

        if year:
            query["expense_date"] = {
                "$gte": Date(year, 1, 1),
                "$lt": Date(year + 1, 1, 1),
            }

        pipeline = [
            {"$match": query},
            {
                "$group": {
                    "_id": "$claim_type_code",
                    "count": {"$sum": 1},
                }
            },
        ]

        results = await self.collection.aggregate(pipeline).to_list(length=None)

        return {
            str(result["_id"]): int(result["count"])
            for result in results
            if result.get("_id") is not None
        }

    async def get_dashboard_statistics(
        self,
        company_id: str = "default",
        from_date: Optional[Date] = None,
        to_date: Optional[Date] = None,
        department_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        claim_type_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get HR/Admin/Finance dashboard statistics.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
        }

        query.update(self._build_date_range_filter(from_date, to_date))

        if department_id:
            query["department_id"] = department_id

        if manager_id:
            query["manager_id"] = manager_id

        if claim_type_id:
            query["claim_type_id"] = claim_type_id

        pipeline = [
            {"$match": query},
            {
                "$group": {
                    "_id": {
                        "status": "$status",
                        "source": "$source",
                        "claim_type_code": "$claim_type_code",
                        "department_name": "$department_name",
                    },
                    "count": {"$sum": 1},
                    "claimed_amount": {"$sum": "$amount"},
                    "approved_amount": {"$sum": {"$ifNull": ["$approved_amount", 0]}},
                    "paid_amount": {"$sum": {"$ifNull": ["$paid_amount", 0]}},
                    "read_only_count": {
                        "$sum": {
                            "$cond": [{"$eq": ["$is_read_only", True]}, 1, 0]
                        }
                    },
                }
            },
        ]

        results = await self.collection.aggregate(pipeline).to_list(length=None)

        dashboard: Dict[str, Any] = {
            "total_claims": 0,
            "pending_approval_count": 0,
            "pending_manager_approval_count": 0,
            "pending_finance_approval_count": 0,
            "approved_count": 0,
            "rejected_count": 0,
            "sent_back_count": 0,
            "processing_count": 0,
            "paid_count": 0,
            "failed_count": 0,
            "total_claimed_amount": 0.0,
            "total_approved_amount": 0.0,
            "total_paid_amount": 0.0,
            "pending_payout_amount": 0.0,
            "claims_by_type": {},
            "claims_by_department": {},
            "claims_by_status": {},
            "claims_by_source": {},
            "read_only_hrms_claims": 0,
            "local_claims": 0,
            "imported_claims": 0,
            "ai_agent_claims": 0,
        }

        pending_statuses = {
            ClaimStatus.PENDING.value,
            ClaimStatus.RESUBMITTED.value,
            ClaimStatus.MANAGER_APPROVED.value,
            ClaimStatus.FINANCE_APPROVED.value,
        }

        for result in results:
            group_id = result["_id"]
            status_value = group_id.get("status")
            source_value = group_id.get("source")
            claim_type_code = group_id.get("claim_type_code") or "UNKNOWN"
            department_name = group_id.get("department_name") or "UNKNOWN"

            count = int(result.get("count", 0))
            claimed_amount = float(result.get("claimed_amount", 0.0))
            approved_amount = float(result.get("approved_amount", 0.0))
            paid_amount = float(result.get("paid_amount", 0.0))
            read_only_count = int(result.get("read_only_count", 0))

            dashboard["total_claims"] += count
            dashboard["total_claimed_amount"] += claimed_amount
            dashboard["total_approved_amount"] += approved_amount
            dashboard["total_paid_amount"] += paid_amount
            dashboard["read_only_hrms_claims"] += read_only_count

            dashboard["claims_by_status"][status_value] = (
                dashboard["claims_by_status"].get(status_value, 0) + count
            )

            dashboard["claims_by_source"][source_value] = (
                dashboard["claims_by_source"].get(source_value, 0) + count
            )

            dashboard["claims_by_type"][claim_type_code] = (
                dashboard["claims_by_type"].get(claim_type_code, 0) + count
            )

            dashboard["claims_by_department"][department_name] = (
                dashboard["claims_by_department"].get(department_name, 0) + count
            )

            if status_value in pending_statuses:
                dashboard["pending_approval_count"] += count

            if status_value == ClaimStatus.PENDING.value:
                dashboard["pending_manager_approval_count"] += count

            if status_value == ClaimStatus.MANAGER_APPROVED.value:
                dashboard["pending_finance_approval_count"] += count

            if status_value == ClaimStatus.APPROVED.value:
                dashboard["approved_count"] += count

            if status_value == ClaimStatus.REJECTED.value:
                dashboard["rejected_count"] += count

            if status_value == ClaimStatus.SENT_BACK.value:
                dashboard["sent_back_count"] += count

            if status_value == ClaimStatus.PROCESSING.value:
                dashboard["processing_count"] += count
                dashboard["pending_payout_amount"] += approved_amount

            if status_value == ClaimStatus.PAID.value:
                dashboard["paid_count"] += count

            if status_value == ClaimStatus.FAILED.value:
                dashboard["failed_count"] += count

            if source_value == ClaimSource.LOCAL.value:
                dashboard["local_claims"] += count

            if source_value == ClaimSource.IMPORTED.value:
                dashboard["imported_claims"] += count

            if source_value == ClaimSource.AI_AGENT.value:
                dashboard["ai_agent_claims"] += count

        return dashboard

    # ---------------------------------------------------------------------
    # Bulk operations
    # ---------------------------------------------------------------------

    async def bulk_update_status(
        self,
        claim_ids: List[str],
        new_status: ClaimStatus,
        extra_updates: Optional[Dict[str, Any]] = None,
        company_id: str = "default",
        prevent_read_only_update: bool = True,
    ) -> int:
        """
        Bulk update claim status.

        Returns modified count.
        """
        normalized_ids = [self._normalize_claim_id(item) for item in claim_ids]

        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
            "claim_id": {"$in": normalized_ids},
        }

        query = self._editable_filter(
            query,
            prevent_read_only_update=prevent_read_only_update,
        )

        update_data: Dict[str, Any] = {
            "status": new_status.value,
            "updated_at": DateTime.utcnow(),
        }

        if extra_updates:
            for key, value in extra_updates.items():
                update_data[key] = self._enum_value(value)

        result = await self.collection.update_many(
            query,
            {"$set": update_data},
        )

        return int(result.modified_count)

    async def bulk_mark_read_only_by_source(
        self,
        source: ClaimSource,
        company_id: str = "default",
        is_read_only: bool = True,
    ) -> int:
        """
        Mark claims read-only by source.

        Useful after HRMS/import sync.
        """
        result = await self.collection.update_many(
            {
                "company_id": self._normalize_company_id(company_id),
                "source": source.value,
            },
            {
                "$set": {
                    "is_read_only": is_read_only,
                    "updated_at": DateTime.utcnow(),
                }
            },
        )

        return int(result.modified_count)