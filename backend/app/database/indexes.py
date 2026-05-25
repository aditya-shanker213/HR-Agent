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
- Unique company settings per company_id
- Unique employee records per company
- Unique leave request records per company
- Unique claim records per company
- Fast master data listing, filtering, searching, and workflow lookups

Pattern:
FastAPI startup -> MongoDB connect -> create_indexes(db)

Important:
Index creation is idempotent.
It is safe to run multiple times because MongoDB will not recreate the same
index again if it already exists.

Note:
For users collection, some existing indexes already use older names:
- idx_active_created
- idx_role
- idx_locked_until_sparse
- idx_last_login

We keep those names to avoid MongoDB IndexOptionsConflict errors.
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
        results["company_settings"] = await self.create_company_settings_indexes()
        results["employees"] = await self.create_employees_indexes()
        results["leave_requests"] = await self.create_leave_requests_indexes()
        results["claims"] = await self.create_claims_indexes()

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

        Important:
        These names match the indexes already present in your MongoDB database.
        Do not rename these unless you first drop old user indexes.
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
                "name": "idx_active_created",
            },
            {
                "keys": [("role", ASCENDING)],
                "name": "idx_role",
            },
            {
                "keys": [("locked_until", ASCENDING)],
                "name": "idx_locked_until_sparse",
                "sparse": True,
            },
            {
                "keys": [("last_login", DESCENDING)],
                "name": "idx_last_login",
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
    # Company Settings indexes
    # -------------------------

    async def create_company_settings_indexes(self) -> Dict[str, Any]:
        """
        Create indexes for company_settings collection.
        """
        index_definitions = [
            {
                "keys": [("company_id", ASCENDING)],
                "name": "idx_company_settings_company_id_unique",
                "unique": True,
            },
            {
                "keys": [("is_active", ASCENDING), ("company_id", ASCENDING)],
                "name": "idx_company_settings_active_company",
            },
            {
                "keys": [("created_at", DESCENDING)],
                "name": "idx_company_settings_created",
            },
            {
                "keys": [("updated_at", DESCENDING)],
                "name": "idx_company_settings_updated",
            },
            {
                "keys": [("company_info.company_name", ASCENDING)],
                "name": "idx_company_settings_company_name",
            },
            {
                "keys": [("system.default_location", ASCENDING)],
                "name": "idx_company_settings_default_location",
                "sparse": True,
            },
            {
                "keys": [("payroll.currency", ASCENDING)],
                "name": "idx_company_settings_currency",
            },
            {
                "keys": [("payroll.pay_cycle", ASCENDING)],
                "name": "idx_company_settings_pay_cycle",
            },
        ]

        return await self._create_indexes_for_collection(
            collection_name="company_settings",
            index_definitions=index_definitions,
        )

    # -------------------------
    # Employees indexes
    # -------------------------

    async def create_employees_indexes(self) -> Dict[str, Any]:
        """
        Create indexes for employees collection.

        Why company_id is included in unique indexes:
        The employee model supports future multi-company usage.
        EMP001 can exist in different companies, but not twice inside the same company.
        """
        index_definitions = [
            {
                "keys": [("company_id", ASCENDING), ("employee_code", ASCENDING)],
                "name": "idx_employees_company_employee_code_unique",
                "unique": True,
            },
            {
                "keys": [("company_id", ASCENDING), ("user_id", ASCENDING)],
                "name": "idx_employees_company_user_id_unique",
                "unique": True,
            },
            {
                "keys": [("company_id", ASCENDING), ("email", ASCENDING)],
                "name": "idx_employees_company_email_unique",
                "unique": True,
            },
            {
                "keys": [("company_id", ASCENDING), ("phone", ASCENDING)],
                "name": "idx_employees_company_phone_unique_sparse",
                "unique": True,
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("is_active", ASCENDING),
                    ("employment_status", ASCENDING),
                ],
                "name": "idx_employees_company_active_status",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("department_id", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                "name": "idx_employees_company_department_active",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("designation_id", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                "name": "idx_employees_company_designation_active",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("manager_id", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                "name": "idx_employees_company_manager_active",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("work_location", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                "name": "idx_employees_company_location_active",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("work_mode", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                "name": "idx_employees_company_work_mode_active",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("employee_type", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                "name": "idx_employees_company_employee_type_active",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("joining_date", DESCENDING),
                ],
                "name": "idx_employees_company_joining_date",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("probation_end_date", ASCENDING),
                ],
                "name": "idx_employees_company_probation_end",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("resignation_date", DESCENDING),
                ],
                "name": "idx_employees_company_resignation_date",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("last_working_date", DESCENDING),
                ],
                "name": "idx_employees_company_last_working_date",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("created_at", DESCENDING),
                ],
                "name": "idx_employees_company_created",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("updated_at", DESCENDING),
                ],
                "name": "idx_employees_company_updated",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("first_name", ASCENDING),
                    ("last_name", ASCENDING),
                ],
                "name": "idx_employees_company_name",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("current_address.city", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                "name": "idx_employees_company_current_city_active",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("current_address.state", ASCENDING),
                    ("is_active", ASCENDING),
                ],
                "name": "idx_employees_company_current_state_active",
                "sparse": True,
            },
            {
                "keys": [
                    ("first_name", TEXT),
                    ("middle_name", TEXT),
                    ("last_name", TEXT),
                    ("employee_code", TEXT),
                    ("email", TEXT),
                    ("personal_email", TEXT),
                    ("phone", TEXT),
                    ("work_location", TEXT),
                ],
                "name": "idx_employees_text_search",
            },
        ]

        return await self._create_indexes_for_collection(
            collection_name="employees",
            index_definitions=index_definitions,
        )

    # -------------------------
    # Leave Requests indexes
    # -------------------------

    async def create_leave_requests_indexes(self) -> Dict[str, Any]:
        """
        Create indexes for leave_requests collection.

        These indexes support:
        - Unique leave request ID per company
        - HRMS imported/read-only leave records
        - Employee leave history
        - Pending approvals
        - Manager/HR dashboards
        - Calendar view
        - Conflict detection
        - Leave statistics
        - Search/filter APIs
        """
        index_definitions = [
            {
                "keys": [("company_id", ASCENDING), ("leave_request_id", ASCENDING)],
                "name": "idx_leave_requests_company_request_id_unique",
                "unique": True,
            },
            {
                "keys": [("company_id", ASCENDING), ("external_hrms_id", ASCENDING)],
                "name": "idx_leave_requests_company_external_hrms_id_unique_sparse",
                "unique": True,
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("employee_id", ASCENDING),
                    ("applied_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_employee_applied",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("employee_id", ASCENDING),
                    ("status", ASCENDING),
                    ("start_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_employee_status_start",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("employee_code", ASCENDING),
                    ("applied_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_employee_code_applied",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("status", ASCENDING),
                    ("applied_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_status_applied",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("current_approver_id", ASCENDING),
                    ("status", ASCENDING),
                    ("applied_date", ASCENDING),
                ],
                "name": "idx_leave_requests_company_approver_status_applied",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("leave_type_id", ASCENDING),
                    ("status", ASCENDING),
                    ("start_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_leave_type_status_start",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("leave_type_code", ASCENDING),
                    ("status", ASCENDING),
                    ("start_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_leave_type_code_status_start",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("department_id", ASCENDING),
                    ("status", ASCENDING),
                    ("start_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_department_status_start",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("manager_id", ASCENDING),
                    ("status", ASCENDING),
                    ("start_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_manager_status_start",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("start_date", ASCENDING),
                    ("end_date", ASCENDING),
                    ("status", ASCENDING),
                ],
                "name": "idx_leave_requests_company_date_range_status",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("employee_id", ASCENDING),
                    ("start_date", ASCENDING),
                    ("end_date", ASCENDING),
                    ("status", ASCENDING),
                ],
                "name": "idx_leave_requests_company_employee_date_range_status",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("source", ASCENDING),
                    ("is_read_only", ASCENDING),
                ],
                "name": "idx_leave_requests_company_source_readonly",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("is_emergency", ASCENDING),
                    ("status", ASCENDING),
                    ("applied_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_emergency_status_applied",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("is_backdated", ASCENDING),
                    ("status", ASCENDING),
                    ("applied_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_backdated_status_applied",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("is_half_day", ASCENDING),
                    ("status", ASCENDING),
                    ("start_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_half_day_status_start",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("has_conflict", ASCENDING),
                    ("status", ASCENDING),
                    ("applied_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_conflict_status_applied",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("documentation_required", ASCENDING),
                    ("documentation_received", ASCENDING),
                    ("status", ASCENDING),
                ],
                "name": "idx_leave_requests_company_documentation_status",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("balance_action", ASCENDING),
                    ("status", ASCENDING),
                ],
                "name": "idx_leave_requests_company_balance_action_status",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("created_at", DESCENDING),
                ],
                "name": "idx_leave_requests_company_created",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("updated_at", DESCENDING),
                ],
                "name": "idx_leave_requests_company_updated",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("approved_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_approved_date",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("rejected_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_rejected_date",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("cancelled_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_cancelled_date",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("withdrawn_date", DESCENDING),
                ],
                "name": "idx_leave_requests_company_withdrawn_date",
                "sparse": True,
            },
            {
                "keys": [
                    ("leave_request_id", TEXT),
                    ("employee_code", TEXT),
                    ("employee_name", TEXT),
                    ("leave_type_code", TEXT),
                    ("leave_type_name", TEXT),
                    ("reason", TEXT),
                    ("department_name", TEXT),
                    ("manager_name", TEXT),
                ],
                "name": "idx_leave_requests_text_search",
            },
        ]

        return await self._create_indexes_for_collection(
            collection_name="leave_requests",
            index_definitions=index_definitions,
        )


    # -------------------------
    # Claims indexes
    # -------------------------

    async def create_claims_indexes(self) -> Dict[str, Any]:
        """
        Create indexes for claims collection.

        These indexes support:
        - Unique claim ID per company
        - HRMS imported/read-only claim records
        - Employee claim history
        - Manager/HR/Finance approval queues
        - Structured approval step lookup
        - Claim type, department, manager, status, source, and payment filters
        - Duplicate detection helper queries
        - Payment processing dashboards
        - Claim statistics and reporting

        Important:
        - Claim auto approval is disabled.
        - Do not create indexes for auto approval workflows.
        """
        index_definitions = [
            {
                "keys": [("company_id", ASCENDING), ("claim_id", ASCENDING)],
                "name": "idx_claims_company_claim_id_unique",
                "unique": True,
            },
            {
                "keys": [("company_id", ASCENDING), ("external_hrms_id", ASCENDING)],
                "name": "idx_claims_company_external_hrms_id_unique_sparse",
                "unique": True,
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("employee_id", ASCENDING),
                    ("created_at", DESCENDING),
                ],
                "name": "idx_claims_company_employee_created",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("employee_id", ASCENDING),
                    ("status", ASCENDING),
                    ("expense_date", DESCENDING),
                ],
                "name": "idx_claims_company_employee_status_expense",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("employee_code", ASCENDING),
                    ("created_at", DESCENDING),
                ],
                "name": "idx_claims_company_employee_code_created",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("status", ASCENDING),
                    ("created_at", DESCENDING),
                ],
                "name": "idx_claims_company_status_created",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("status", ASCENDING),
                    ("expense_date", DESCENDING),
                ],
                "name": "idx_claims_company_status_expense",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("claim_type_id", ASCENDING),
                    ("status", ASCENDING),
                    ("expense_date", DESCENDING),
                ],
                "name": "idx_claims_company_claim_type_status_expense",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("claim_type_code", ASCENDING),
                    ("status", ASCENDING),
                    ("expense_date", DESCENDING),
                ],
                "name": "idx_claims_company_claim_type_code_status_expense",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("department_id", ASCENDING),
                    ("status", ASCENDING),
                    ("expense_date", DESCENDING),
                ],
                "name": "idx_claims_company_department_status_expense",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("manager_id", ASCENDING),
                    ("status", ASCENDING),
                    ("expense_date", DESCENDING),
                ],
                "name": "idx_claims_company_manager_status_expense",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("priority", ASCENDING),
                    ("status", ASCENDING),
                    ("created_at", ASCENDING),
                ],
                "name": "idx_claims_company_priority_status_created",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("payment_status", ASCENDING),
                    ("status", ASCENDING),
                    ("updated_at", DESCENDING),
                ],
                "name": "idx_claims_company_payment_status_updated",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("source", ASCENDING),
                    ("is_read_only", ASCENDING),
                ],
                "name": "idx_claims_company_source_readonly",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("amount", ASCENDING),
                    ("status", ASCENDING),
                ],
                "name": "idx_claims_company_amount_status",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("approved_amount", ASCENDING),
                    ("status", ASCENDING),
                ],
                "name": "idx_claims_company_approved_amount_status",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("paid_amount", ASCENDING),
                    ("payment_status", ASCENDING),
                ],
                "name": "idx_claims_company_paid_amount_payment_status",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("expense_date", ASCENDING),
                    ("status", ASCENDING),
                ],
                "name": "idx_claims_company_expense_date_status",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("created_at", DESCENDING),
                ],
                "name": "idx_claims_company_created",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("updated_at", DESCENDING),
                ],
                "name": "idx_claims_company_updated",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("submitted_at", DESCENDING),
                ],
                "name": "idx_claims_company_submitted_at",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("approved_at", DESCENDING),
                ],
                "name": "idx_claims_company_approved_at",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("rejected_at", DESCENDING),
                ],
                "name": "idx_claims_company_rejected_at",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("cancelled_at", DESCENDING),
                ],
                "name": "idx_claims_company_cancelled_at",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("withdrawn_at", DESCENDING),
                ],
                "name": "idx_claims_company_withdrawn_at",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("payment_date", DESCENDING),
                ],
                "name": "idx_claims_company_payment_date",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("synced_to_hrms", ASCENDING),
                    ("synced_at", DESCENDING),
                ],
                "name": "idx_claims_company_hrms_sync",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("approval_steps.approval_status", ASCENDING),
                    ("approval_steps.approver_role", ASCENDING),
                    ("created_at", ASCENDING),
                ],
                "name": "idx_claims_company_approval_status_role_created",
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("approval_steps.approver_id", ASCENDING),
                    ("approval_steps.approval_status", ASCENDING),
                    ("created_at", ASCENDING),
                ],
                "name": "idx_claims_company_approval_approver_status_created",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("current_approval_role", ASCENDING),
                    ("status", ASCENDING),
                    ("created_at", ASCENDING),
                ],
                "name": "idx_claims_company_current_approval_role_status_created",
                "sparse": True,
            },
            {
                "keys": [
                    ("company_id", ASCENDING),
                    ("employee_id", ASCENDING),
                    ("claim_type_id", ASCENDING),
                    ("expense_date", ASCENDING),
                    ("amount", ASCENDING),
                    ("created_at", DESCENDING),
                ],
                "name": "idx_claims_duplicate_detection",
            },
            {
                "keys": [
                    ("claim_id", TEXT),
                    ("employee_code", TEXT),
                    ("employee_name", TEXT),
                    ("claim_type_code", TEXT),
                    ("claim_type_name", TEXT),
                    ("title", TEXT),
                    ("description", TEXT),
                    ("vendor_name", TEXT),
                    ("bill_number", TEXT),
                    ("department_name", TEXT),
                    ("manager_name", TEXT),
                ],
                "name": "idx_claims_text_search",
            },
        ]

        return await self._create_indexes_for_collection(
            collection_name="claims",
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