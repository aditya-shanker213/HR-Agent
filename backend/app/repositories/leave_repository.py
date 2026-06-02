"""
Leave repository - MongoDB operations for leave_requests collection.

Pattern:
Route → Service → Repository → MongoDB

This repository handles:
- CRUD operations for leave requests
- Leave request ID generation
- Find by various filters
- List with pagination
- Search functionality
- Approval workflow queries
- Leave statistics
- Calendar queries
- Conflict detection
- Balance tracking updates

Important:
- Repository only handles database operations.
- Business validation stays in leave_service.py.
- Leave model validation stays in leave_model.py.
- Routes should not write MongoDB queries directly.

Production/MVP note:
- In MVP/local mode, this repository stores leave workflow records in MongoDB.
- In production HRMS read-only mode, service layer may bypass this repository
  and read leave data from HRMS provider instead.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError


class LeaveRepository:
    """
    Repository for leave_requests collection.
    """

    BLOCKED_UPDATE_FIELDS = {
        "_id",
        "id",
        "leave_request_id",
        "employee_id",
        "employee_code",
        "company_id",
        "source",
        "external_hrms_id",
        "created_at",
        "created_by",
    }

    VALID_SORT_FIELDS = {
        "leave_request_id",
        "employee_code",
        "employee_name",
        "start_date",
        "end_date",
        "applied_date",
        "status",
        "leave_type_code",
        "leave_type_name",
        "total_days",
        "created_at",
        "updated_at",
    }

    FINAL_STATUSES = {
        "approved",
        "rejected",
        "cancelled",
        "withdrawn",
    }

    ACTIVE_OR_PENDING_STATUSES = {
        "pending",
        "manager_approved",
        "approved",
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.leave_requests

    # -------------------------
    # Internal helpers
    # -------------------------

    def _to_object_id(self, value: str) -> Optional[ObjectId]:
        """
        Safely convert string ID to MongoDB ObjectId.
        """
        try:
            return ObjectId(str(value))
        except (InvalidId, TypeError):
            return None

    def _convert_id(self, document: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Convert MongoDB ObjectId to string.
        """
        if document and "_id" in document:
            document["_id"] = str(document["_id"])
            document["id"] = document["_id"]

        return document

    def _convert_many(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert ObjectId for many documents.
        """
        return [self._convert_id(document) for document in documents if document]

    def _normalize_company_id(self, company_id: Optional[str] = "default") -> str:
        """
        Normalize company_id.
        """
        if not company_id:
            return "default"

        company_id = str(company_id).strip().lower()

        if not company_id:
            return "default"

        if not company_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "company_id can contain only letters, numbers, hyphen, and underscore"
            )

        return company_id

    def _normalize_code(self, value: Optional[str]) -> Optional[str]:
        """
        Normalize codes like leave_request_id, employee_code, leave_type_code.
        """
        if value is None:
            return None

        value = str(value).strip().upper()
        return value or None

    def _normalize_status(self, status: Optional[str]) -> Optional[str]:
        """
        Normalize leave status.
        """
        if status is None:
            return None

        status = str(status).strip().lower()
        return status or None

    def _normalize_text(self, value: Optional[str]) -> Optional[str]:
        """
        Normalize optional text fields.
        """
        if value is None:
            return None

        value = str(value).strip()
        return value or None

    def _clean_pagination(self, skip: int = 0, limit: int = 100) -> Tuple[int, int]:
        """
        Clamp pagination values.
        """
        skip = max(skip, 0)
        limit = max(1, min(limit, 500))
        return skip, limit

    def _clean_sort(
        self,
        sort_by: str = "applied_date",
        sort_order: str = "desc",
    ) -> Tuple[str, int]:
        """
        Validate and normalize sort field/order.
        """
        sort_by = str(sort_by).strip()

        if sort_by not in self.VALID_SORT_FIELDS:
            sort_by = "applied_date"

        sort_direction = DESCENDING if str(sort_order).lower() == "desc" else ASCENDING

        return sort_by, sort_direction

    def _clean_update_data(self, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove blocked fields and normalize update payload.
        """
        cleaned: Dict[str, Any] = {}

        for key, value in update_data.items():
            if key in self.BLOCKED_UPDATE_FIELDS:
                continue

            cleaned[key] = value

        cleaned["updated_at"] = datetime.utcnow()

        return cleaned

    def _build_base_query(
        self,
        company_id: str = "default",
        employee_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build common query with company_id and optional employee filter.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
        }

        if employee_id:
            query["employee_id"] = employee_id

        return query

    def _apply_date_range_filter(
        self,
        query: Dict[str, Any],
        start_date_from: Optional[date] = None,
        start_date_to: Optional[date] = None,
        field_name: str = "start_date",
    ) -> Dict[str, Any]:
        """
        Add date range filter to query.
        """
        if start_date_from or start_date_to:
            date_query: Dict[str, Any] = {}

            if start_date_from:
                date_query["$gte"] = start_date_from

            if start_date_to:
                date_query["$lte"] = start_date_to

            if date_query:
                query[field_name] = date_query

        return query

    # -------------------------
    # Leave request ID generation
    # -------------------------

    async def generate_leave_request_id(
        self,
        prefix: str = "LV",
        company_id: str = "default",
        year: Optional[int] = None,
    ) -> str:
        """
        Generate unique leave request ID.

        Pattern:
            LV-2026-0001
            LV-2026-0002
        """
        company_id = self._normalize_company_id(company_id)

        prefix = str(prefix).strip().upper()
        if not prefix:
            prefix = "LV"

        if year is None:
            year = datetime.utcnow().year

        pattern = f"^{re.escape(prefix)}-{year}-[0-9]+$"

        last_request = await self.collection.find_one(
            {
                "company_id": company_id,
                "leave_request_id": {"$regex": pattern},
            },
            sort=[("leave_request_id", DESCENDING)],
            projection={"leave_request_id": 1},
        )

        if not last_request:
            return f"{prefix}-{year}-0001"

        last_id = str(last_request.get("leave_request_id", f"{prefix}-{year}-0000"))

        try:
            parts = last_id.split("-")
            if len(parts) >= 3:
                last_number = int(parts[-1])
                next_number = last_number + 1
                return f"{prefix}-{year}-{next_number:04d}"

        except (ValueError, IndexError):
            pass

        return f"{prefix}-{year}-0001"

    # -------------------------
    # Create
    # -------------------------

    async def create(self, leave_data: Dict[str, Any]) -> str:
        """
        Create new leave request.
        """
        try:
            leave_data.setdefault("created_at", datetime.utcnow())
            leave_data.setdefault("updated_at", datetime.utcnow())

            result = await self.collection.insert_one(leave_data)
            return str(result.inserted_id)

        except DuplicateKeyError:
            raise

    # -------------------------
    # Read operations
    # -------------------------

    async def find_by_id(
        self,
        leave_id: str,
        company_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find leave request by MongoDB _id.
        """
        object_id = self._to_object_id(leave_id)

        if object_id is None:
            return None

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        leave = await self.collection.find_one(query)
        return self._convert_id(leave)

    async def find_by_leave_request_id(
        self,
        leave_request_id: str,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Find leave request by leave_request_id.
        """
        normalized_id = self._normalize_code(leave_request_id)

        if not normalized_id:
            return None

        leave = await self.collection.find_one(
            {
                "company_id": self._normalize_company_id(company_id),
                "leave_request_id": normalized_id,
            }
        )

        return self._convert_id(leave)

    async def find_by_external_hrms_id(
        self,
        external_hrms_id: str,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Find leave request by external HRMS ID.
        Useful for imported/read-only HRMS records.
        """
        external_hrms_id = self._normalize_text(external_hrms_id)

        if not external_hrms_id:
            return None

        leave = await self.collection.find_one(
            {
                "company_id": self._normalize_company_id(company_id),
                "external_hrms_id": external_hrms_id,
            }
        )

        return self._convert_id(leave)

    async def list_by_employee(
        self,
        employee_id: str,
        company_id: str = "default",
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
        sort_by: str = "applied_date",
        sort_order: str = "desc",
    ) -> List[Dict[str, Any]]:
        """
        List leave requests for an employee.
        """
        skip, limit = self._clean_pagination(skip, limit)
        sort_by, sort_direction = self._clean_sort(sort_by, sort_order)

        query = self._build_base_query(company_id, employee_id)

        normalized_status = self._normalize_status(status)
        if normalized_status:
            query["status"] = normalized_status

        cursor = (
            self.collection.find(query)
            .sort(sort_by, sort_direction)
            .skip(skip)
            .limit(limit)
        )

        leaves = await cursor.to_list(length=limit)
        return self._convert_many(leaves)

    async def list_with_filters(
        self,
        company_id: str = "default",
        employee_id: Optional[str] = None,
        employee_code: Optional[str] = None,
        status: Optional[str] = None,
        statuses: Optional[List[str]] = None,
        leave_type_id: Optional[str] = None,
        leave_type_code: Optional[str] = None,
        department_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        current_approver_id: Optional[str] = None,
        source: Optional[str] = None,
        is_read_only: Optional[bool] = None,
        start_date_from: Optional[date] = None,
        start_date_to: Optional[date] = None,
        applied_date_from: Optional[date] = None,
        applied_date_to: Optional[date] = None,
        is_emergency: Optional[bool] = None,
        is_backdated: Optional[bool] = None,
        is_half_day: Optional[bool] = None,
        has_conflict: Optional[bool] = None,
        documentation_required: Optional[bool] = None,
        documentation_received: Optional[bool] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
        sort_by: str = "applied_date",
        sort_order: str = "desc",
    ) -> List[Dict[str, Any]]:
        """
        List leave requests with multiple filters.
        """
        skip, limit = self._clean_pagination(skip, limit)
        sort_by, sort_direction = self._clean_sort(sort_by, sort_order)

        query = self._build_base_query(company_id, employee_id)

        normalized_status = self._normalize_status(status)
        if normalized_status:
            query["status"] = normalized_status

        if statuses:
            cleaned_statuses = [
                status_value
                for status_value in [self._normalize_status(item) for item in statuses]
                if status_value
            ]
            if cleaned_statuses:
                query["status"] = {"$in": cleaned_statuses}

        normalized_employee_code = self._normalize_code(employee_code)
        if normalized_employee_code:
            query["employee_code"] = normalized_employee_code

        if leave_type_id:
            query["leave_type_id"] = leave_type_id

        normalized_leave_type_code = self._normalize_code(leave_type_code)
        if normalized_leave_type_code:
            query["leave_type_code"] = normalized_leave_type_code

        if department_id:
            query["department_id"] = department_id

        if manager_id:
            query["manager_id"] = manager_id

        if current_approver_id:
            query["current_approver_id"] = current_approver_id

        if source:
            query["source"] = str(source).strip().lower()

        if is_read_only is not None:
            query["is_read_only"] = is_read_only

        query = self._apply_date_range_filter(
            query=query,
            start_date_from=start_date_from,
            start_date_to=start_date_to,
            field_name="start_date",
        )

        query = self._apply_date_range_filter(
            query=query,
            start_date_from=applied_date_from,
            start_date_to=applied_date_to,
            field_name="applied_date",
        )

        if is_emergency is not None:
            query["is_emergency"] = is_emergency

        if is_backdated is not None:
            query["is_backdated"] = is_backdated

        if is_half_day is not None:
            query["is_half_day"] = is_half_day

        if has_conflict is not None:
            query["has_conflict"] = has_conflict

        if documentation_required is not None:
            query["documentation_required"] = documentation_required

        if documentation_received is not None:
            query["documentation_received"] = documentation_received

        search = self._normalize_text(search)
        if search:
            query["$or"] = [
                {"leave_request_id": {"$regex": re.escape(search), "$options": "i"}},
                {"employee_code": {"$regex": re.escape(search), "$options": "i"}},
                {"employee_name": {"$regex": re.escape(search), "$options": "i"}},
                {"leave_type_code": {"$regex": re.escape(search), "$options": "i"}},
                {"leave_type_name": {"$regex": re.escape(search), "$options": "i"}},
                {"reason": {"$regex": re.escape(search), "$options": "i"}},
            ]

        cursor = (
            self.collection.find(query)
            .sort(sort_by, sort_direction)
            .skip(skip)
            .limit(limit)
        )

        leaves = await cursor.to_list(length=limit)
        return self._convert_many(leaves)

    async def count_with_filters(
        self,
        company_id: str = "default",
        employee_id: Optional[str] = None,
        employee_code: Optional[str] = None,
        status: Optional[str] = None,
        statuses: Optional[List[str]] = None,
        leave_type_id: Optional[str] = None,
        leave_type_code: Optional[str] = None,
        department_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        current_approver_id: Optional[str] = None,
        source: Optional[str] = None,
        is_read_only: Optional[bool] = None,
        start_date_from: Optional[date] = None,
        start_date_to: Optional[date] = None,
        applied_date_from: Optional[date] = None,
        applied_date_to: Optional[date] = None,
        is_emergency: Optional[bool] = None,
        is_backdated: Optional[bool] = None,
        is_half_day: Optional[bool] = None,
        has_conflict: Optional[bool] = None,
        documentation_required: Optional[bool] = None,
        documentation_received: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> int:
        """
        Count leave requests with same filters as list_with_filters.
        """
        query = self._build_base_query(company_id, employee_id)

        normalized_status = self._normalize_status(status)
        if normalized_status:
            query["status"] = normalized_status

        if statuses:
            cleaned_statuses = [
                status_value
                for status_value in [self._normalize_status(item) for item in statuses]
                if status_value
            ]
            if cleaned_statuses:
                query["status"] = {"$in": cleaned_statuses}

        normalized_employee_code = self._normalize_code(employee_code)
        if normalized_employee_code:
            query["employee_code"] = normalized_employee_code

        if leave_type_id:
            query["leave_type_id"] = leave_type_id

        normalized_leave_type_code = self._normalize_code(leave_type_code)
        if normalized_leave_type_code:
            query["leave_type_code"] = normalized_leave_type_code

        if department_id:
            query["department_id"] = department_id

        if manager_id:
            query["manager_id"] = manager_id

        if current_approver_id:
            query["current_approver_id"] = current_approver_id

        if source:
            query["source"] = str(source).strip().lower()

        if is_read_only is not None:
            query["is_read_only"] = is_read_only

        query = self._apply_date_range_filter(
            query=query,
            start_date_from=start_date_from,
            start_date_to=start_date_to,
            field_name="start_date",
        )

        query = self._apply_date_range_filter(
            query=query,
            start_date_from=applied_date_from,
            start_date_to=applied_date_to,
            field_name="applied_date",
        )

        if is_emergency is not None:
            query["is_emergency"] = is_emergency

        if is_backdated is not None:
            query["is_backdated"] = is_backdated

        if is_half_day is not None:
            query["is_half_day"] = is_half_day

        if has_conflict is not None:
            query["has_conflict"] = has_conflict

        if documentation_required is not None:
            query["documentation_required"] = documentation_required

        if documentation_received is not None:
            query["documentation_received"] = documentation_received

        search = self._normalize_text(search)
        if search:
            query["$or"] = [
                {"leave_request_id": {"$regex": re.escape(search), "$options": "i"}},
                {"employee_code": {"$regex": re.escape(search), "$options": "i"}},
                {"employee_name": {"$regex": re.escape(search), "$options": "i"}},
                {"leave_type_code": {"$regex": re.escape(search), "$options": "i"}},
                {"leave_type_name": {"$regex": re.escape(search), "$options": "i"}},
                {"reason": {"$regex": re.escape(search), "$options": "i"}},
            ]

        return await self.collection.count_documents(query)

    async def list_pending_approvals(
        self,
        approver_id: str,
        company_id: str = "default",
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List leaves pending approval for a specific approver.
        """
        skip, limit = self._clean_pagination(skip, limit)

        query = {
            "company_id": self._normalize_company_id(company_id),
            "current_approver_id": approver_id,
            "status": {"$in": ["pending", "manager_approved"]},
        }

        cursor = (
            self.collection.find(query)
            .sort("applied_date", ASCENDING)
            .skip(skip)
            .limit(limit)
        )

        leaves = await cursor.to_list(length=limit)
        return self._convert_many(leaves)

    async def count_pending_approvals(
        self,
        approver_id: str,
        company_id: str = "default",
    ) -> int:
        """
        Count leaves pending approval for a specific approver.
        """
        query = {
            "company_id": self._normalize_company_id(company_id),
            "current_approver_id": approver_id,
            "status": {"$in": ["pending", "manager_approved"]},
        }

        return await self.collection.count_documents(query)

    async def list_by_status(
        self,
        status: str,
        company_id: str = "default",
        employee_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List leave requests by status.
        """
        skip, limit = self._clean_pagination(skip, limit)

        query = self._build_base_query(company_id, employee_id)

        normalized_status = self._normalize_status(status)
        if not normalized_status:
            return []

        query["status"] = normalized_status

        cursor = (
            self.collection.find(query)
            .sort("applied_date", DESCENDING)
            .skip(skip)
            .limit(limit)
        )

        leaves = await cursor.to_list(length=limit)
        return self._convert_many(leaves)

    async def list_upcoming_leaves(
        self,
        employee_id: str,
        company_id: str = "default",
        from_date: Optional[date] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        List upcoming approved leaves for an employee.
        """
        if from_date is None:
            from_date = date.today()

        limit = max(1, min(limit, 100))

        query = {
            "company_id": self._normalize_company_id(company_id),
            "employee_id": employee_id,
            "status": "approved",
            "start_date": {"$gte": from_date},
        }

        cursor = (
            self.collection.find(query)
            .sort("start_date", ASCENDING)
            .limit(limit)
        )

        leaves = await cursor.to_list(length=limit)
        return self._convert_many(leaves)

    async def list_leaves_in_range(
        self,
        start_date: date,
        end_date: date,
        company_id: str = "default",
        employee_id: Optional[str] = None,
        department_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        status: Optional[str] = None,
        statuses: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        List leaves that overlap with a date range.

        Leaves overlap if:
            leave.start_date <= range.end_date
            AND
            leave.end_date >= range.start_date
        """
        query = self._build_base_query(company_id, employee_id)

        query["$and"] = [
            {"start_date": {"$lte": end_date}},
            {"end_date": {"$gte": start_date}},
        ]

        normalized_status = self._normalize_status(status)
        if normalized_status:
            query["status"] = normalized_status

        if statuses:
            cleaned_statuses = [
                status_value
                for status_value in [self._normalize_status(item) for item in statuses]
                if status_value
            ]
            if cleaned_statuses:
                query["status"] = {"$in": cleaned_statuses}

        if department_id:
            query["department_id"] = department_id

        if manager_id:
            query["manager_id"] = manager_id

        cursor = self.collection.find(query).sort("start_date", ASCENDING)

        leaves = await cursor.to_list(length=None)
        return self._convert_many(leaves)

    async def get_calendar_leaves(
        self,
        start_date: date,
        end_date: date,
        company_id: str = "default",
        department_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        include_pending: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get leave records for calendar view.
        """
        statuses = ["approved"]

        if include_pending:
            statuses.extend(["pending", "manager_approved"])

        return await self.list_leaves_in_range(
            start_date=start_date,
            end_date=end_date,
            company_id=company_id,
            department_id=department_id,
            manager_id=manager_id,
            statuses=statuses,
        )

    # -------------------------
    # Update operations
    # -------------------------

    async def update(
        self,
        leave_id: str,
        update_data: Dict[str, Any],
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Update leave request fields.
        """
        object_id = self._to_object_id(leave_id)

        if object_id is None:
            return False

        safe_update = self._clean_update_data(update_data)

        if not safe_update:
            return False

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        # Do not allow local updates to HRMS read-only records.
        query["is_read_only"] = {"$ne": True}

        result = await self.collection.update_one(query, {"$set": safe_update})
        return result.matched_count > 0

    async def update_status(
        self,
        leave_id: str,
        status: str,
        updated_by: Optional[str] = None,
        company_id: Optional[str] = None,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update leave status.
        """
        object_id = self._to_object_id(leave_id)

        if object_id is None:
            return False

        normalized_status = self._normalize_status(status)

        if not normalized_status:
            return False

        update_data: Dict[str, Any] = {
            "status": normalized_status,
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = updated_by

        if extra_fields:
            for key, value in extra_fields.items():
                if key not in self.BLOCKED_UPDATE_FIELDS:
                    update_data[key] = value

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        query["is_read_only"] = {"$ne": True}

        result = await self.collection.update_one(query, {"$set": update_data})
        return result.matched_count > 0

    async def update_approval_chain(
        self,
        leave_id: str,
        approval_chain: List[Dict[str, Any]],
        current_approver_id: Optional[str],
        updated_by: Optional[str] = None,
        company_id: Optional[str] = None,
        status: Optional[str] = None,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update leave approval chain and current approver.
        """
        object_id = self._to_object_id(leave_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "approval_chain": approval_chain,
            "current_approver_id": current_approver_id,
            "updated_at": datetime.utcnow(),
        }

        if status:
            normalized_status = self._normalize_status(status)
            if normalized_status:
                update_data["status"] = normalized_status

        if updated_by:
            update_data["updated_by"] = updated_by

        if extra_fields:
            for key, value in extra_fields.items():
                if key not in self.BLOCKED_UPDATE_FIELDS:
                    update_data[key] = value

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        query["is_read_only"] = {"$ne": True}

        result = await self.collection.update_one(query, {"$set": update_data})
        return result.matched_count > 0

    async def update_balance_tracking(
        self,
        leave_id: str,
        balance_reserved: Optional[float] = None,
        balance_after: Optional[float] = None,
        balance_action: Optional[str] = None,
        updated_by: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Update leave balance tracking fields.
        """
        object_id = self._to_object_id(leave_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "updated_at": datetime.utcnow(),
        }

        if balance_reserved is not None:
            update_data["balance_reserved"] = balance_reserved

        if balance_after is not None:
            update_data["balance_after"] = balance_after

        if balance_action is not None:
            update_data["balance_action"] = str(balance_action).strip().lower()

        if updated_by:
            update_data["updated_by"] = updated_by

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        query["is_read_only"] = {"$ne": True}

        result = await self.collection.update_one(query, {"$set": update_data})
        return result.matched_count > 0

    async def mark_conflict_status(
        self,
        leave_id: str,
        has_conflict: bool,
        conflict_leave_request_ids: Optional[List[str]] = None,
        updated_by: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Mark conflict status for a leave request.
        """
        object_id = self._to_object_id(leave_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "has_conflict": has_conflict,
            "conflict_leave_request_ids": conflict_leave_request_ids or [],
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = updated_by

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        query["is_read_only"] = {"$ne": True}

        result = await self.collection.update_one(query, {"$set": update_data})
        return result.matched_count > 0

    # -------------------------
    # Count and statistics
    # -------------------------

    async def count_by_employee(
        self,
        employee_id: str,
        company_id: str = "default",
        status: Optional[str] = None,
    ) -> int:
        """
        Count leave requests for an employee.
        """
        query = self._build_base_query(company_id, employee_id)

        normalized_status = self._normalize_status(status)
        if normalized_status:
            query["status"] = normalized_status

        return await self.collection.count_documents(query)

    async def count_by_status(
        self,
        status: str,
        company_id: str = "default",
        employee_id: Optional[str] = None,
    ) -> int:
        """
        Count leave requests by status.
        """
        query = self._build_base_query(company_id, employee_id)

        normalized_status = self._normalize_status(status)

        if not normalized_status:
            return 0

        query["status"] = normalized_status

        return await self.collection.count_documents(query)

    async def count_all(
        self,
        company_id: str = "default",
        employee_id: Optional[str] = None,
    ) -> int:
        """
        Count all leave requests.
        """
        query = self._build_base_query(company_id, employee_id)
        return await self.collection.count_documents(query)

    async def get_leave_statistics(
        self,
        employee_id: str,
        company_id: str = "default",
        year: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get leave statistics for an employee.
        """
        if year is None:
            year = datetime.utcnow().year

        query = self._build_base_query(company_id, employee_id)
        query["start_date"] = {
            "$gte": date(year, 1, 1),
            "$lte": date(year, 12, 31),
        }

        pipeline = [
            {"$match": query},
            {
                "$group": {
                    "_id": "$status",
                    "count": {"$sum": 1},
                    "total_days": {"$sum": "$total_days"},
                }
            },
        ]

        results = await self.collection.aggregate(pipeline).to_list(length=None)

        stats = {
            "company_id": self._normalize_company_id(company_id),
            "employee_id": employee_id,
            "year": year,
            "total_requests": 0,
            "total_days_taken": 0.0,
            "pending": 0,
            "manager_approved": 0,
            "approved": 0,
            "rejected": 0,
            "cancelled": 0,
            "withdrawn": 0,
        }

        for result in results:
            status_key = str(result.get("_id") or "unknown")
            count = int(result.get("count", 0))
            days = float(result.get("total_days", 0.0) or 0.0)

            stats["total_requests"] += count

            if status_key in stats:
                stats[status_key] = count

            if status_key == "approved":
                stats["total_days_taken"] += days

        return stats

    async def get_dashboard_statistics(
        self,
        company_id: str = "default",
        year: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get company-wide leave dashboard statistics.
        """
        company_id = self._normalize_company_id(company_id)

        query: Dict[str, Any] = {
            "company_id": company_id,
        }

        if year is not None:
            query["start_date"] = {
                "$gte": date(year, 1, 1),
                "$lte": date(year, 12, 31),
            }

        pipeline = [
            {"$match": query},
            {
                "$group": {
                    "_id": "$status",
                    "count": {"$sum": 1},
                }
            },
        ]

        results = await self.collection.aggregate(pipeline).to_list(length=None)

        stats = {
            "company_id": company_id,
            "total_requests": 0,
            "pending_requests": 0,
            "manager_approved_requests": 0,
            "approved_requests": 0,
            "rejected_requests": 0,
            "cancelled_requests": 0,
            "withdrawn_requests": 0,
            "emergency_requests": 0,
            "backdated_requests": 0,
            "documentation_pending": 0,
        }

        status_key_map = {
            "pending": "pending_requests",
            "manager_approved": "manager_approved_requests",
            "approved": "approved_requests",
            "rejected": "rejected_requests",
            "cancelled": "cancelled_requests",
            "withdrawn": "withdrawn_requests",
        }

        for result in results:
            status_key = str(result.get("_id") or "unknown")
            count = int(result.get("count", 0))

            stats["total_requests"] += count

            mapped_key = status_key_map.get(status_key)
            if mapped_key:
                stats[mapped_key] = count

        extra_match = {
            "company_id": company_id,
        }

        if year is not None:
            extra_match["start_date"] = {
                "$gte": date(year, 1, 1),
                "$lte": date(year, 12, 31),
            }

        stats["emergency_requests"] = await self.collection.count_documents(
            {**extra_match, "is_emergency": True}
        )
        stats["backdated_requests"] = await self.collection.count_documents(
            {**extra_match, "is_backdated": True}
        )
        stats["documentation_pending"] = await self.collection.count_documents(
            {
                **extra_match,
                "documentation_required": True,
                "documentation_received": False,
                "status": {"$in": ["pending", "manager_approved"]},
            }
        )

        return stats

    async def get_statistics_by_leave_type(
        self,
        company_id: str = "default",
        year: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get leave statistics grouped by leave type.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
        }

        if year is not None:
            query["start_date"] = {
                "$gte": date(year, 1, 1),
                "$lte": date(year, 12, 31),
            }

        pipeline = [
            {"$match": query},
            {
                "$group": {
                    "_id": "$leave_type_code",
                    "leave_type_name": {"$first": "$leave_type_name"},
                    "request_count": {"$sum": 1},
                    "approved_count": {
                        "$sum": {
                            "$cond": [{"$eq": ["$status", "approved"]}, 1, 0]
                        }
                    },
                    "approved_days": {
                        "$sum": {
                            "$cond": [{"$eq": ["$status", "approved"]}, "$total_days", 0]
                        }
                    },
                }
            },
            {"$sort": {"request_count": -1}},
        ]

        return await self.collection.aggregate(pipeline).to_list(length=None)

    async def exists_by_leave_request_id(
        self,
        leave_request_id: str,
        company_id: str = "default",
    ) -> bool:
        """
        Check if leave request ID exists.
        """
        normalized_id = self._normalize_code(leave_request_id)

        if not normalized_id:
            return False

        count = await self.collection.count_documents(
            {
                "company_id": self._normalize_company_id(company_id),
                "leave_request_id": normalized_id,
            },
            limit=1,
        )

        return count > 0

    async def exists_by_external_hrms_id(
        self,
        external_hrms_id: str,
        company_id: str = "default",
    ) -> bool:
        """
        Check if external HRMS leave record exists.
        """
        external_hrms_id = self._normalize_text(external_hrms_id)

        if not external_hrms_id:
            return False

        count = await self.collection.count_documents(
            {
                "company_id": self._normalize_company_id(company_id),
                "external_hrms_id": external_hrms_id,
            },
            limit=1,
        )

        return count > 0

    # -------------------------
    # Conflict detection
    # -------------------------

    async def find_overlapping_leaves(
        self,
        employee_id: str,
        start_date: date,
        end_date: date,
        company_id: str = "default",
        exclude_leave_id: Optional[str] = None,
        statuses: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find overlapping approved/pending leaves for an employee.
        """
        if statuses is None:
            statuses = ["pending", "manager_approved", "approved"]

        query = {
            "company_id": self._normalize_company_id(company_id),
            "employee_id": employee_id,
            "status": {"$in": [self._normalize_status(item) for item in statuses if item]},
            "$and": [
                {"start_date": {"$lte": end_date}},
                {"end_date": {"$gte": start_date}},
            ],
        }

        if exclude_leave_id:
            object_id = self._to_object_id(exclude_leave_id)
            if object_id:
                query["_id"] = {"$ne": object_id}

        cursor = self.collection.find(query).sort("start_date", ASCENDING)

        leaves = await cursor.to_list(length=None)
        return self._convert_many(leaves)

    async def has_overlapping_leave(
        self,
        employee_id: str,
        start_date: date,
        end_date: date,
        company_id: str = "default",
        exclude_leave_id: Optional[str] = None,
    ) -> bool:
        """
        Check whether employee has overlapping active leave.
        """
        overlaps = await self.find_overlapping_leaves(
            employee_id=employee_id,
            start_date=start_date,
            end_date=end_date,
            company_id=company_id,
            exclude_leave_id=exclude_leave_id,
        )

        return len(overlaps) > 0