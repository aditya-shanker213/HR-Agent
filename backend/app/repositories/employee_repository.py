"""
Employee repository - MongoDB operations for employees collection.

Pattern:
Route → Service → Repository → MongoDB

This repository handles:
- CRUD operations for employees
- Employee code generation
- Find by user_id, employee_code, email
- List with filters
- Search by name, email, phone, code
- Pagination support
- Manager-subordinate queries
- Probation / notice period / exit queries
- Leave balance and claim limit updates
- Statistics

Important:
- Repository only handles database operations.
- Business validation should stay in employee_service.py.
- Employee model validation should stay in employee_model.py.
- Routes should not write MongoDB queries directly.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError


class EmployeeRepository:
    """
    Repository for employees collection.

    Collection:
        employees
    """

    BLOCKED_UPDATE_FIELDS = {
        "_id",
        "id",
        "employee_code",
        "user_id",
        "company_id",
        "created_at",
        "created_by",
    }

    OPTIONAL_TEXT_FIELDS = {
        "middle_name",
        "personal_email",
        "alternate_phone",
        "manager_id",
        "pan_number",
        "aadhaar_number",
        "passport_number",
        "driving_license",
        "created_by",
        "updated_by",
    }

    VALID_SORT_FIELDS = {
        "employee_code",
        "first_name",
        "last_name",
        "email",
        "joining_date",
        "created_at",
        "updated_at",
        "employment_status",
        "work_location",
    }

    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection = db.employees

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

    def _convert_id(
        self,
        document: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Convert MongoDB ObjectId to string.

        Keeps both:
        - _id as string
        - id as string
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
        Convert ObjectId for many documents.
        """
        return [self._convert_id(document) for document in documents if document]

    def _convert_dates_for_mongo(self, value: Any) -> Any:
        """
        Recursively convert Python date objects to datetime objects for MongoDB.

        MongoDB can store datetime, but not datetime.date directly.
        This fixes errors like:
        Invalid document: cannot encode object: datetime.date(...)
        """
        if isinstance(value, datetime):
            return value

        if isinstance(value, date):
            return datetime.combine(value, time.min)

        if isinstance(value, dict):
            return {
                key: self._convert_dates_for_mongo(item)
                for key, item in value.items()
            }

        if isinstance(value, list):
            return [self._convert_dates_for_mongo(item) for item in value]

        return value

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

    def _normalize_optional_text(self, value: Optional[str]) -> Optional[str]:
        """
        Strip optional text and convert empty string to None.
        """
        if value is None:
            return None

        value = str(value).strip()
        return value or None

    def _normalize_employee_code(self, employee_code: str) -> str:
        """
        Normalize employee code.
        """
        employee_code = str(employee_code).strip().upper()

        if not employee_code:
            raise ValueError("employee_code cannot be empty")

        return employee_code

    def _normalize_email(self, email: str) -> str:
        """
        Normalize email.
        """
        return str(email).strip().lower()

    def _normalize_work_location(self, work_location: str) -> str:
        """
        Normalize work location for consistent filtering.
        """
        return str(work_location).strip().title()

    def _safe_regex(self, value: str) -> str:
        """
        Escape user search input before using regex.
        """
        return re.escape(str(value).strip())

    def _clean_pagination(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> Tuple[int, int]:
        """
        Clamp pagination values.
        """
        skip = max(skip, 0)
        limit = max(1, min(limit, 500))
        return skip, limit

    def _clean_sort(
        self,
        sort_by: str = "employee_code",
        sort_order: str = "asc",
    ) -> Tuple[str, int]:
        """
        Validate and normalize sort field/order.
        """
        sort_by = str(sort_by).strip()

        if sort_by not in self.VALID_SORT_FIELDS:
            sort_by = "employee_code"

        sort_direction = DESCENDING if str(sort_order).lower() == "desc" else ASCENDING

        return sort_by, sort_direction

    def _clean_insert_data(self, employee_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize employee data before insert.
        """
        cleaned = dict(employee_data)

        cleaned["company_id"] = self._normalize_company_id(
            cleaned.get("company_id", "default")
        )

        if "employee_code" in cleaned:
            cleaned["employee_code"] = self._normalize_employee_code(
                cleaned["employee_code"]
            )

        if "email" in cleaned:
            cleaned["email"] = self._normalize_email(cleaned["email"])

        if "work_location" in cleaned:
            cleaned["work_location"] = self._normalize_work_location(
                cleaned["work_location"]
            )

        for field in self.OPTIONAL_TEXT_FIELDS:
            if field in cleaned:
                cleaned[field] = self._normalize_optional_text(cleaned[field])

        cleaned.setdefault("is_active", True)
        cleaned.setdefault("employment_status", "probation")
        cleaned.setdefault("employee_type", "full_time")
        cleaned.setdefault("work_mode", "office")
        cleaned.setdefault("leave_balances", [])
        cleaned.setdefault("claim_limits", [])

        now = datetime.utcnow()
        cleaned["created_at"] = now
        cleaned["updated_at"] = now

        return self._convert_dates_for_mongo(cleaned)

    def _clean_update_data(self, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove blocked fields and normalize update payload.
        """
        cleaned: Dict[str, Any] = {}

        for key, value in update_data.items():
            if key in self.BLOCKED_UPDATE_FIELDS:
                continue

            cleaned[key] = value

        if "email" in cleaned:
            cleaned["email"] = self._normalize_email(cleaned["email"])

        if "work_location" in cleaned:
            cleaned["work_location"] = self._normalize_work_location(
                cleaned["work_location"]
            )

        for field in self.OPTIONAL_TEXT_FIELDS:
            if field in cleaned:
                cleaned[field] = self._normalize_optional_text(cleaned[field])

        cleaned["updated_at"] = datetime.utcnow()

        return self._convert_dates_for_mongo(cleaned)

    def _build_base_query(
        self,
        company_id: str = "default",
        is_active: Optional[bool] = True,
    ) -> Dict[str, Any]:
        """
        Build common query with company_id and active filter.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
        }

        if is_active is not None:
            query["is_active"] = is_active

        return query

    # -------------------------
    # Employee code generation
    # -------------------------

    async def generate_employee_code(
        self,
        prefix: str = "EMP",
        company_id: str = "default",
        min_digits: int = 3,
    ) -> str:
        """
        Generate unique employee code.

        Pattern:
            EMP001, EMP002, EMP003

        Note:
            This method is safe for normal usage, but under very high concurrency,
            the unique index must still protect employee_code at database level.
        """
        company_id = self._normalize_company_id(company_id)

        prefix = str(prefix).strip().upper()

        if not prefix:
            prefix = "EMP"

        if not prefix.replace("_", "").replace("-", "").isalnum():
            raise ValueError("prefix can contain only letters, numbers, hyphen, and underscore")

        pattern = f"^{re.escape(prefix)}[0-9]+$"

        last_employee = await self.collection.find_one(
            {
                "company_id": company_id,
                "employee_code": {"$regex": pattern},
            },
            sort=[("employee_code", DESCENDING)],
            projection={"employee_code": 1},
        )

        if not last_employee:
            return f"{prefix}{1:0{min_digits}d}"

        last_code = str(last_employee.get("employee_code", f"{prefix}0"))

        try:
            last_number = int(last_code.replace(prefix, "", 1))
            next_number = last_number + 1
            return f"{prefix}{next_number:0{min_digits}d}"

        except ValueError:
            return f"{prefix}{1:0{min_digits}d}"

    # -------------------------
    # Create
    # -------------------------

    async def create(self, employee_data: Dict[str, Any]) -> str:
        """
        Create new employee.

        Raises:
            DuplicateKeyError if unique indexes are violated.
        """
        cleaned_data = self._clean_insert_data(employee_data)

        try:
            result = await self.collection.insert_one(cleaned_data)
            return str(result.inserted_id)

        except DuplicateKeyError:
            raise

    async def create_many(
        self,
        employees_data: List[Dict[str, Any]],
    ) -> List[str]:
        """
        Bulk create employees.

        Use carefully from service layer after validation.
        """
        if not employees_data:
            return []

        cleaned_records = [
            self._clean_insert_data(employee_data)
            for employee_data in employees_data
        ]

        try:
            result = await self.collection.insert_many(cleaned_records, ordered=False)
            return [str(inserted_id) for inserted_id in result.inserted_ids]

        except DuplicateKeyError:
            raise

    # -------------------------
    # Read operations
    # -------------------------

    async def find_by_id(
        self,
        employee_id: str,
        company_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Find employee by MongoDB _id.
        """
        object_id = self._to_object_id(employee_id)

        if object_id is None:
            return None

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        employee = await self.collection.find_one(query)
        return self._convert_id(employee)

    async def find_active_by_id(
        self,
        employee_id: str,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Find active employee by ID.
        """
        object_id = self._to_object_id(employee_id)

        if object_id is None:
            return None

        employee = await self.collection.find_one(
            {
                "_id": object_id,
                "company_id": self._normalize_company_id(company_id),
                "is_active": True,
            }
        )

        return self._convert_id(employee)

    async def find_by_employee_code(
        self,
        employee_code: str,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Find employee by employee code.
        """
        employee = await self.collection.find_one(
            {
                "company_id": self._normalize_company_id(company_id),
                "employee_code": self._normalize_employee_code(employee_code),
            }
        )

        return self._convert_id(employee)

    async def find_by_user_id(
        self,
        user_id: str,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Find employee by user_id.
        """
        employee = await self.collection.find_one(
            {
                "company_id": self._normalize_company_id(company_id),
                "user_id": str(user_id),
            }
        )

        return self._convert_id(employee)

    async def find_by_email(
        self,
        email: str,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Find employee by official email.
        """
        employee = await self.collection.find_one(
            {
                "company_id": self._normalize_company_id(company_id),
                "email": self._normalize_email(email),
            }
        )

        return self._convert_id(employee)

    async def find_by_personal_email(
        self,
        personal_email: str,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Find employee by personal email.
        """
        employee = await self.collection.find_one(
            {
                "company_id": self._normalize_company_id(company_id),
                "personal_email": self._normalize_email(personal_email),
            }
        )

        return self._convert_id(employee)

    async def find_by_phone(
        self,
        phone: str,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Find employee by phone.
        """
        employee = await self.collection.find_one(
            {
                "company_id": self._normalize_company_id(company_id),
                "phone": str(phone).strip(),
            }
        )

        return self._convert_id(employee)

    # -------------------------
    # Listing and filtering
    # -------------------------

    async def list_all(
        self,
        company_id: str = "default",
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100,
        sort_by: str = "employee_code",
        sort_order: str = "asc",
    ) -> List[Dict[str, Any]]:
        """
        List all employees with pagination.
        """
        skip, limit = self._clean_pagination(skip, limit)
        sort_by, sort_direction = self._clean_sort(sort_by, sort_order)

        query = self._build_base_query(company_id, is_active)

        cursor = (
            self.collection.find(query)
            .sort(sort_by, sort_direction)
            .skip(skip)
            .limit(limit)
        )

        employees = await cursor.to_list(length=limit)
        return self._convert_many(employees)

    async def list_with_filters(
        self,
        company_id: str = "default",
        department_id: Optional[str] = None,
        designation_id: Optional[str] = None,
        manager_id: Optional[str] = None,
        employment_status: Optional[str] = None,
        employee_type: Optional[str] = None,
        work_location: Optional[str] = None,
        work_mode: Optional[str] = None,
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100,
        sort_by: str = "employee_code",
        sort_order: str = "asc",
    ) -> List[Dict[str, Any]]:
        """
        List employees using multiple optional filters.
        """
        skip, limit = self._clean_pagination(skip, limit)
        sort_by, sort_direction = self._clean_sort(sort_by, sort_order)

        query = self._build_base_query(company_id, is_active)

        if department_id:
            query["department_id"] = department_id

        if designation_id:
            query["designation_id"] = designation_id

        if manager_id:
            query["manager_id"] = manager_id

        if employment_status:
            query["employment_status"] = str(employment_status).strip().lower()

        if employee_type:
            query["employee_type"] = str(employee_type).strip().lower()

        if work_location:
            query["work_location"] = self._normalize_work_location(work_location)

        if work_mode:
            query["work_mode"] = str(work_mode).strip().lower()

        cursor = (
            self.collection.find(query)
            .sort(sort_by, sort_direction)
            .skip(skip)
            .limit(limit)
        )

        employees = await cursor.to_list(length=limit)
        return self._convert_many(employees)

    async def list_by_department(
        self,
        department_id: str,
        company_id: str = "default",
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List employees by department.
        """
        return await self.list_with_filters(
            company_id=company_id,
            department_id=department_id,
            is_active=is_active,
            skip=skip,
            limit=limit,
        )

    async def list_by_designation(
        self,
        designation_id: str,
        company_id: str = "default",
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List employees by designation.
        """
        return await self.list_with_filters(
            company_id=company_id,
            designation_id=designation_id,
            is_active=is_active,
            skip=skip,
            limit=limit,
        )

    async def list_by_manager(
        self,
        manager_id: str,
        company_id: str = "default",
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List employees reporting to a manager.
        """
        return await self.list_with_filters(
            company_id=company_id,
            manager_id=manager_id,
            is_active=is_active,
            skip=skip,
            limit=limit,
        )

    async def list_by_location(
        self,
        work_location: str,
        company_id: str = "default",
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List employees by work location.
        """
        return await self.list_with_filters(
            company_id=company_id,
            work_location=work_location,
            is_active=is_active,
            skip=skip,
            limit=limit,
        )

    async def list_by_status(
        self,
        employment_status: str,
        company_id: str = "default",
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List employees by employment status.
        """
        return await self.list_with_filters(
            company_id=company_id,
            employment_status=employment_status,
            is_active=is_active,
            skip=skip,
            limit=limit,
        )

    async def search(
        self,
        search_term: str,
        company_id: str = "default",
        is_active: Optional[bool] = True,
        department_id: Optional[str] = None,
        designation_id: Optional[str] = None,
        employment_status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Search employees by:
        - first_name
        - middle_name
        - last_name
        - employee_code
        - email
        - personal_email
        - phone
        """
        skip, limit = self._clean_pagination(skip, limit)

        search_term = str(search_term).strip()

        query = self._build_base_query(company_id, is_active)

        if search_term:
            safe_term = self._safe_regex(search_term)

            query["$or"] = [
                {"first_name": {"$regex": safe_term, "$options": "i"}},
                {"middle_name": {"$regex": safe_term, "$options": "i"}},
                {"last_name": {"$regex": safe_term, "$options": "i"}},
                {"employee_code": {"$regex": safe_term, "$options": "i"}},
                {"email": {"$regex": safe_term, "$options": "i"}},
                {"personal_email": {"$regex": safe_term, "$options": "i"}},
                {"phone": {"$regex": safe_term, "$options": "i"}},
            ]

        if department_id:
            query["department_id"] = department_id

        if designation_id:
            query["designation_id"] = designation_id

        if employment_status:
            query["employment_status"] = str(employment_status).strip().lower()

        cursor = (
            self.collection.find(query)
            .sort("employee_code", ASCENDING)
            .skip(skip)
            .limit(limit)
        )

        employees = await cursor.to_list(length=limit)
        return self._convert_many(employees)

    # -------------------------
    # Special lists
    # -------------------------

    async def list_on_probation(
        self,
        company_id: str = "default",
        include_expired_probation: bool = True,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List employees currently marked as probation.

        include_expired_probation=True also shows employees whose probation_end_date has passed,
        because HR may need to confirm them.
        """
        skip, limit = self._clean_pagination(skip, limit)

        query = self._build_base_query(company_id, True)
        query["employment_status"] = "probation"

        if not include_expired_probation:
            query["probation_end_date"] = {
                "$gte": datetime.combine(date.today(), time.min)
            }

        cursor = (
            self.collection.find(query)
            .sort("probation_end_date", ASCENDING)
            .skip(skip)
            .limit(limit)
        )

        employees = await cursor.to_list(length=limit)
        return self._convert_many(employees)

    async def list_probation_ending_soon(
        self,
        company_id: str = "default",
        days: int = 15,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List employees whose probation ends soon.
        """
        skip, limit = self._clean_pagination(skip, limit)

        today = date.today()
        end_date = today + timedelta(days=max(days, 0))

        query = self._build_base_query(company_id, True)
        query["employment_status"] = "probation"
        query["probation_end_date"] = {
            "$gte": datetime.combine(today, time.min),
            "$lte": datetime.combine(end_date, time.max),
        }

        cursor = (
            self.collection.find(query)
            .sort("probation_end_date", ASCENDING)
            .skip(skip)
            .limit(limit)
        )

        employees = await cursor.to_list(length=limit)
        return self._convert_many(employees)

    async def list_on_notice_period(
        self,
        company_id: str = "default",
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List employees on notice period.
        """
        return await self.list_with_filters(
            company_id=company_id,
            employment_status="notice_period",
            is_active=True,
            skip=skip,
            limit=limit,
            sort_by="last_working_date",
            sort_order="asc",
        )

    async def list_exited_employees(
        self,
        company_id: str = "default",
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List employees who have exited.
        """
        skip, limit = self._clean_pagination(skip, limit)

        query = {
            "company_id": self._normalize_company_id(company_id),
            "employment_status": {
                "$in": ["resigned", "terminated", "absconded", "retired"],
            },
        }

        cursor = (
            self.collection.find(query)
            .sort("last_working_date", DESCENDING)
            .skip(skip)
            .limit(limit)
        )

        employees = await cursor.to_list(length=limit)
        return self._convert_many(employees)

    async def list_for_dropdown(
        self,
        company_id: str = "default",
        is_active: Optional[bool] = True,
        department_id: Optional[str] = None,
        manager_only: bool = False,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        List employees for dropdown/select options.

        Returns minimal fields.
        """
        _, limit = self._clean_pagination(0, limit)

        query = self._build_base_query(company_id, is_active)

        if department_id:
            query["department_id"] = department_id

        if manager_only:
            query["employment_status"] = {"$in": ["active", "probation", "notice_period"]}

        projection = {
            "_id": 1,
            "company_id": 1,
            "employee_code": 1,
            "first_name": 1,
            "middle_name": 1,
            "last_name": 1,
            "email": 1,
            "designation_id": 1,
            "department_id": 1,
            "employment_status": 1,
            "is_active": 1,
        }

        cursor = (
            self.collection.find(query, projection)
            .sort("employee_code", ASCENDING)
            .limit(limit)
        )

        employees = await cursor.to_list(length=limit)
        return self._convert_many(employees)

    # -------------------------
    # Manager / hierarchy helpers
    # -------------------------

    async def has_direct_reports(
        self,
        manager_id: str,
        company_id: str = "default",
        is_active: Optional[bool] = True,
    ) -> bool:
        """
        Check if employee has direct reports.
        """
        query = self._build_base_query(company_id, is_active)
        query["manager_id"] = manager_id

        count = await self.collection.count_documents(query, limit=1)
        return count > 0

    async def count_direct_reports(
        self,
        manager_id: str,
        company_id: str = "default",
        is_active: Optional[bool] = True,
    ) -> int:
        """
        Count direct reports of a manager.
        """
        query = self._build_base_query(company_id, is_active)
        query["manager_id"] = manager_id

        return await self.collection.count_documents(query)

    async def get_direct_report_ids(
        self,
        manager_id: str,
        company_id: str = "default",
        is_active: Optional[bool] = True,
    ) -> List[str]:
        """
        Get direct report employee IDs.
        """
        query = self._build_base_query(company_id, is_active)
        query["manager_id"] = manager_id

        cursor = self.collection.find(query, {"_id": 1})
        employees = await cursor.to_list(length=None)

        return [str(employee["_id"]) for employee in employees]

    # -------------------------
    # Update
    # -------------------------

    async def update(
        self,
        employee_id: str,
        update_data: Dict[str, Any],
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Update employee fields.
        """
        object_id = self._to_object_id(employee_id)

        if object_id is None:
            return False

        safe_update = self._clean_update_data(update_data)

        if not safe_update:
            return False

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        result = await self.collection.update_one(
            query,
            {"$set": safe_update},
        )

        return result.matched_count > 0

    async def update_by_employee_code(
        self,
        employee_code: str,
        update_data: Dict[str, Any],
        company_id: str = "default",
    ) -> bool:
        """
        Update employee by employee_code.
        """
        safe_update = self._clean_update_data(update_data)

        if not safe_update:
            return False

        result = await self.collection.update_one(
            {
                "company_id": self._normalize_company_id(company_id),
                "employee_code": self._normalize_employee_code(employee_code),
            },
            {"$set": safe_update},
        )

        return result.matched_count > 0

    async def update_employment_status(
        self,
        employee_id: str,
        status: str,
        updated_by: Optional[str] = None,
        company_id: Optional[str] = None,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update employment status.

        extra_fields can include:
        - resignation_date
        - last_working_date
        - confirmation_date
        """
        update_data: Dict[str, Any] = {
            "employment_status": str(status).strip().lower(),
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

        if extra_fields:
            for key, value in extra_fields.items():
                if key not in self.BLOCKED_UPDATE_FIELDS:
                    update_data[key] = value

        update_data = self._convert_dates_for_mongo(update_data)

        object_id = self._to_object_id(employee_id)

        if object_id is None:
            return False

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        result = await self.collection.update_one(
            query,
            {"$set": update_data},
        )

        return result.matched_count > 0

    async def update_manager(
        self,
        employee_id: str,
        manager_id: Optional[str],
        updated_by: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Update employee manager.
        """
        update_data: Dict[str, Any] = {
            "manager_id": self._normalize_optional_text(manager_id),
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

        update_data = self._convert_dates_for_mongo(update_data)

        object_id = self._to_object_id(employee_id)

        if object_id is None:
            return False

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        result = await self.collection.update_one(
            query,
            {"$set": update_data},
        )

        return result.matched_count > 0

    async def update_leave_balances(
        self,
        employee_id: str,
        leave_balances: List[Dict[str, Any]],
        updated_by: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Replace leave balances.
        """
        object_id = self._to_object_id(employee_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "leave_balances": leave_balances,
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

        update_data = self._convert_dates_for_mongo(update_data)

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        result = await self.collection.update_one(
            query,
            {"$set": update_data},
        )

        return result.matched_count > 0

    async def update_claim_limits(
        self,
        employee_id: str,
        claim_limits: List[Dict[str, Any]],
        updated_by: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Replace claim limits.
        """
        object_id = self._to_object_id(employee_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "claim_limits": claim_limits,
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

        update_data = self._convert_dates_for_mongo(update_data)

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        result = await self.collection.update_one(
            query,
            {"$set": update_data},
        )

        return result.matched_count > 0

    async def patch_leave_balance(
        self,
        employee_id: str,
        leave_type_id: str,
        year: int,
        balance_update: Dict[str, Any],
        updated_by: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Patch one leave balance item inside leave_balances array.

        Service layer must validate values before calling this.
        """
        object_id = self._to_object_id(employee_id)

        if object_id is None:
            return False

        set_data: Dict[str, Any] = {
            f"leave_balances.$.{key}": value
            for key, value in balance_update.items()
        }

        set_data["updated_at"] = datetime.utcnow()

        if updated_by:
            set_data["updated_by"] = self._normalize_optional_text(updated_by)

        set_data = self._convert_dates_for_mongo(set_data)

        query: Dict[str, Any] = {
            "_id": object_id,
            "leave_balances.leave_type_id": leave_type_id,
            "leave_balances.year": year,
        }

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        result = await self.collection.update_one(
            query,
            {"$set": set_data},
        )

        return result.matched_count > 0

    async def patch_claim_limit(
        self,
        employee_id: str,
        claim_type_id: str,
        year: int,
        claim_update: Dict[str, Any],
        updated_by: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Patch one claim limit item inside claim_limits array.

        Service layer must validate values before calling this.
        """
        object_id = self._to_object_id(employee_id)

        if object_id is None:
            return False

        set_data: Dict[str, Any] = {
            f"claim_limits.$.{key}": value
            for key, value in claim_update.items()
        }

        set_data["updated_at"] = datetime.utcnow()

        if updated_by:
            set_data["updated_by"] = self._normalize_optional_text(updated_by)

        set_data = self._convert_dates_for_mongo(set_data)

        query: Dict[str, Any] = {
            "_id": object_id,
            "claim_limits.claim_type_id": claim_type_id,
            "claim_limits.year": year,
        }

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        result = await self.collection.update_one(
            query,
            {"$set": set_data},
        )

        return result.matched_count > 0

    # -------------------------
    # Activate / Deactivate
    # -------------------------

    async def deactivate(
        self,
        employee_id: str,
        updated_by: Optional[str] = None,
        company_id: Optional[str] = None,
        employment_status: str = "terminated",
    ) -> bool:
        """
        Soft delete employee.

        Also sets employment_status by default to terminated.
        Service layer can pass resigned/retired/etc. when needed.
        """
        object_id = self._to_object_id(employee_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "is_active": False,
            "employment_status": str(employment_status).strip().lower(),
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

        update_data = self._convert_dates_for_mongo(update_data)

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        result = await self.collection.update_one(
            query,
            {"$set": update_data},
        )

        return result.matched_count > 0

    async def activate(
        self,
        employee_id: str,
        updated_by: Optional[str] = None,
        company_id: Optional[str] = None,
        employment_status: str = "active",
    ) -> bool:
        """
        Reactivate employee.
        """
        object_id = self._to_object_id(employee_id)

        if object_id is None:
            return False

        update_data: Dict[str, Any] = {
            "is_active": True,
            "employment_status": str(employment_status).strip().lower(),
            "updated_at": datetime.utcnow(),
        }

        if updated_by:
            update_data["updated_by"] = self._normalize_optional_text(updated_by)

        update_data = self._convert_dates_for_mongo(update_data)

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        result = await self.collection.update_one(
            query,
            {"$set": update_data},
        )

        return result.matched_count > 0

    # -------------------------
    # Existence checks
    # -------------------------

    async def exists_by_id(
        self,
        employee_id: str,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Check if employee exists by ID.
        """
        object_id = self._to_object_id(employee_id)

        if object_id is None:
            return False

        query: Dict[str, Any] = {"_id": object_id}

        if company_id is not None:
            query["company_id"] = self._normalize_company_id(company_id)

        count = await self.collection.count_documents(query, limit=1)
        return count > 0

    async def exists_by_employee_code(
        self,
        employee_code: str,
        company_id: str = "default",
        exclude_employee_id: Optional[str] = None,
    ) -> bool:
        """
        Check if employee code exists.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
            "employee_code": self._normalize_employee_code(employee_code),
        }

        if exclude_employee_id:
            object_id = self._to_object_id(exclude_employee_id)
            if object_id is not None:
                query["_id"] = {"$ne": object_id}

        count = await self.collection.count_documents(query, limit=1)
        return count > 0

    async def exists_by_user_id(
        self,
        user_id: str,
        company_id: str = "default",
        exclude_employee_id: Optional[str] = None,
    ) -> bool:
        """
        Check if user already has an employee profile.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
            "user_id": str(user_id),
        }

        if exclude_employee_id:
            object_id = self._to_object_id(exclude_employee_id)
            if object_id is not None:
                query["_id"] = {"$ne": object_id}

        count = await self.collection.count_documents(query, limit=1)
        return count > 0

    async def exists_by_email(
        self,
        email: str,
        company_id: str = "default",
        exclude_employee_id: Optional[str] = None,
    ) -> bool:
        """
        Check if official email is already used.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
            "email": self._normalize_email(email),
        }

        if exclude_employee_id:
            object_id = self._to_object_id(exclude_employee_id)
            if object_id is not None:
                query["_id"] = {"$ne": object_id}

        count = await self.collection.count_documents(query, limit=1)
        return count > 0

    async def exists_by_phone(
        self,
        phone: str,
        company_id: str = "default",
        exclude_employee_id: Optional[str] = None,
    ) -> bool:
        """
        Check if phone is already used.
        """
        query: Dict[str, Any] = {
            "company_id": self._normalize_company_id(company_id),
            "phone": str(phone).strip(),
        }

        if exclude_employee_id:
            object_id = self._to_object_id(exclude_employee_id)
            if object_id is not None:
                query["_id"] = {"$ne": object_id}

        count = await self.collection.count_documents(query, limit=1)
        return count > 0

    # -------------------------
    # Count and statistics
    # -------------------------

    async def count_all(
        self,
        company_id: str = "default",
        is_active: Optional[bool] = True,
    ) -> int:
        """
        Count employees.
        """
        query = self._build_base_query(company_id, is_active)
        return await self.collection.count_documents(query)

    async def count_by_department(
        self,
        department_id: str,
        company_id: str = "default",
        is_active: Optional[bool] = True,
    ) -> int:
        """
        Count employees in a department.
        """
        query = self._build_base_query(company_id, is_active)
        query["department_id"] = department_id

        return await self.collection.count_documents(query)

    async def count_by_designation(
        self,
        designation_id: str,
        company_id: str = "default",
        is_active: Optional[bool] = True,
    ) -> int:
        """
        Count employees by designation.
        """
        query = self._build_base_query(company_id, is_active)
        query["designation_id"] = designation_id

        return await self.collection.count_documents(query)

    async def count_by_status(
        self,
        employment_status: str,
        company_id: str = "default",
        is_active: Optional[bool] = True,
    ) -> int:
        """
        Count employees by employment status.
        """
        query = self._build_base_query(company_id, is_active)
        query["employment_status"] = str(employment_status).strip().lower()

        return await self.collection.count_documents(query)

    async def get_statistics(
        self,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Get employee statistics.
        """
        company_id = self._normalize_company_id(company_id)

        total = await self.count_all(company_id=company_id, is_active=None)
        active = await self.count_all(company_id=company_id, is_active=True)
        inactive = await self.count_all(company_id=company_id, is_active=False)

        on_probation = await self.count_by_status(
            "probation",
            company_id=company_id,
            is_active=True,
        )

        confirmed = await self.count_by_status(
            "active",
            company_id=company_id,
            is_active=True,
        )

        notice_period = await self.count_by_status(
            "notice_period",
            company_id=company_id,
            is_active=True,
        )

        resigned = await self.count_by_status(
            "resigned",
            company_id=company_id,
            is_active=None,
        )

        terminated = await self.count_by_status(
            "terminated",
            company_id=company_id,
            is_active=None,
        )

        absconded = await self.count_by_status(
            "absconded",
            company_id=company_id,
            is_active=None,
        )

        retired = await self.count_by_status(
            "retired",
            company_id=company_id,
            is_active=None,
        )

        return {
            "company_id": company_id,
            "total_employees": total,
            "active_employees": active,
            "inactive_employees": inactive,
            "on_probation": on_probation,
            "confirmed_employees": confirmed,
            "notice_period": notice_period,
            "resigned_employees": resigned,
            "terminated_employees": terminated,
            "absconded_employees": absconded,
            "retired_employees": retired,
        }

    async def get_department_statistics(
        self,
        company_id: str = "default",
        is_active: Optional[bool] = True,
    ) -> List[Dict[str, Any]]:
        """
        Count employees grouped by department_id.
        """
        match_query = self._build_base_query(company_id, is_active)

        pipeline = [
            {"$match": match_query},
            {
                "$group": {
                    "_id": "$department_id",
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"count": -1}},
        ]

        return await self.collection.aggregate(pipeline).to_list(length=None)

    async def get_status_statistics(
        self,
        company_id: str = "default",
    ) -> List[Dict[str, Any]]:
        """
        Count employees grouped by employment_status.
        """
        pipeline = [
            {
                "$match": {
                    "company_id": self._normalize_company_id(company_id),
                }
            },
            {
                "$group": {
                    "_id": "$employment_status",
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"count": -1}},
        ]

        return await self.collection.aggregate(pipeline).to_list(length=None)

    # -------------------------
    # Utility helpers
    # -------------------------

    async def get_employee_basic_projection(
        self,
        employee_id: str,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """
        Get lightweight employee fields.

        Useful for manager names, dropdowns, approvals, notifications.
        """
        object_id = self._to_object_id(employee_id)

        if object_id is None:
            return None

        projection = {
            "_id": 1,
            "company_id": 1,
            "employee_code": 1,
            "first_name": 1,
            "middle_name": 1,
            "last_name": 1,
            "email": 1,
            "department_id": 1,
            "designation_id": 1,
            "manager_id": 1,
            "employment_status": 1,
            "is_active": 1,
        }

        employee = await self.collection.find_one(
            {
                "_id": object_id,
                "company_id": self._normalize_company_id(company_id),
            },
            projection,
        )

        return self._convert_id(employee)

    async def get_employees_by_ids(
        self,
        employee_ids: List[str],
        company_id: str = "default",
        is_active: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get employees by multiple IDs.
        """
        object_ids = [
            self._to_object_id(employee_id)
            for employee_id in employee_ids
        ]

        object_ids = [object_id for object_id in object_ids if object_id is not None]

        if not object_ids:
            return []

        query = self._build_base_query(company_id, is_active)
        query["_id"] = {"$in": object_ids}

        cursor = self.collection.find(query).sort("employee_code", ASCENDING)

        employees = await cursor.to_list(length=None)
        return self._convert_many(employees)