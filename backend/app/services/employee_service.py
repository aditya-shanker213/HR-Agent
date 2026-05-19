"""
Employee service - Business logic for employee management.

Pattern:
Route → Service → Repository → MongoDB

This service handles:
- Employee creation with validation
- Leave balance initialization from leave types
- Claim limit initialization from claim types
- Manager validation
- Department/designation validation
- User-employee relationship validation
- Employee profile updates
- Employment status management
- Data enrichment
- Safe employee responses

Important:
- Routes should handle HTTP request/response and auth dependencies only.
- Service should handle business rules and validation.
- Repository should handle MongoDB operations only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from backend.app.models.employee_model import Employee, EmploymentStatus
from backend.app.repositories.claim_type_repository import ClaimTypeRepository
from backend.app.repositories.company_settings_repository import CompanySettingsRepository
from backend.app.repositories.department_repository import DepartmentRepository
from backend.app.repositories.designation_repository import DesignationRepository
from backend.app.repositories.employee_repository import EmployeeRepository
from backend.app.repositories.leave_type_repository import LeaveTypeRepository
from backend.app.repositories.user_repository import UserRepository
from backend.app.schemas.employee_schema import (
    CreateEmployeeRequest,
    EmployeeCreatedResponse,
    EmployeeDepartmentStatisticsItem,
    EmployeeDepartmentStatisticsResponse,
    EmployeeDropdownListResponse,
    EmployeeDropdownResponse,
    EmployeeFilterParams,
    EmployeeListResponse,
    EmployeeManagerListResponse,
    EmployeeManagerOptionResponse,
    EmployeePrivateResponse,
    EmployeeResponse,
    EmployeeSearchParams,
    EmployeeStatisticsResponse,
    EmployeeStatusResponse,
    EmployeeStatusStatisticsItem,
    EmployeeStatusStatisticsResponse,
    EmployeeSummaryResponse,
    EmployeeUpdatedResponse,
    UpdateBankDetailsRequest,
    UpdateClaimLimitsRequest,
    UpdateEmergencyContactRequest,
    UpdateEmployeeAddressRequest,
    UpdateEmployeeRequest,
    UpdateEmploymentStatusRequest,
    UpdateLeaveBalancesRequest,
    UpdateManagerRequest,
)


class EmployeeService:
    """
    Service layer for employee operations.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self.repository = EmployeeRepository(db)
        self.user_repository = UserRepository(db)
        self.department_repository = DepartmentRepository(db)
        self.designation_repository = DesignationRepository(db)
        self.leave_type_repository = LeaveTypeRepository(db)
        self.claim_type_repository = ClaimTypeRepository(db)
        self.company_settings_repository = CompanySettingsRepository(db)

    # -------------------------
    # Internal helpers
    # -------------------------

    def _normalize_company_id(self, company_id: Optional[str] = "default") -> str:
        if not company_id:
            return "default"

        company_id = str(company_id).strip().lower()

        if not company_id:
            return "default"

        if not company_id.replace("_", "").replace("-", "").isalnum():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="company_id can contain only letters, numbers, hyphen, and underscore",
            )

        return company_id

    def _full_name(self, employee: Dict[str, Any]) -> str:
        parts = [
            employee.get("first_name"),
            employee.get("middle_name"),
            employee.get("last_name"),
        ]
        return " ".join(str(part).strip() for part in parts if part)

    def _mask_value(
        self,
        value: Optional[str],
        visible_last: int = 4,
    ) -> Optional[str]:
        if not value:
            return None

        value = str(value)

        if len(value) <= visible_last:
            return "*" * len(value)

        return "*" * (len(value) - visible_last) + value[-visible_last:]

    def _model_dump(
        self,
        request: Any,
        exclude_unset: bool = False,
        exclude_none: bool = False,
    ) -> Dict[str, Any]:
        return request.model_dump(
            exclude_unset=exclude_unset,
            exclude_none=exclude_none,
        )

    def _validate_employee_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate final employee payload using Employee model before DB write.
        """
        try:
            validated = Employee(**payload)
            return validated.model_dump()

        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=exc.errors(),
            )

        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

    async def _get_employee_or_404(
        self,
        employee_id: str,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        company_id = self._normalize_company_id(company_id)

        employee = await self.repository.find_by_id(
            employee_id=employee_id,
            company_id=company_id,
        )

        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Employee not found: {employee_id}",
            )

        return employee

    async def _get_employee_by_code_or_404(
        self,
        employee_code: str,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        company_id = self._normalize_company_id(company_id)

        employee = await self.repository.find_by_employee_code(
            employee_code=employee_code,
            company_id=company_id,
        )

        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Employee not found: {employee_code}",
            )

        return employee

    async def _validate_user_available(
        self,
        user_id: str,
        company_id: str,
    ) -> None:
        user = await self.user_repository.find_by_id(user_id)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User not found: {user_id}",
            )

        if not user.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User is inactive: {user_id}",
            )

        if await self.repository.exists_by_user_id(
            user_id=user_id,
            company_id=company_id,
        ):
            existing_employee = await self.repository.find_by_user_id(
                user_id=user_id,
                company_id=company_id,
            )

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "User already has an employee profile: "
                    f"{existing_employee.get('employee_code') if existing_employee else user_id}"
                ),
            )

    async def _validate_department(
        self,
        department_id: str,
    ) -> Dict[str, Any]:
        department = await self.department_repository.find_by_id(department_id)

        if not department:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department not found: {department_id}",
            )

        if not department.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Department is inactive: {department.get('name', department_id)}",
            )

        return department

    async def _validate_designation(
        self,
        designation_id: str,
        department_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        designation = await self.designation_repository.find_by_id(designation_id)

        if not designation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Designation not found: {designation_id}",
            )

        if not designation.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Designation is inactive: {designation.get('name', designation_id)}",
            )

        designation_department_id = designation.get("department_id")

        if department_id and designation_department_id:
            if designation_department_id != department_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Designation does not belong to the selected department",
                )

        return designation

    async def _validate_manager(
        self,
        manager_id: Optional[str],
        employee_code: Optional[str] = None,
        company_id: str = "default",
    ) -> Optional[Dict[str, Any]]:
        if not manager_id:
            return None

        company_id = self._normalize_company_id(company_id)

        manager = await self.repository.find_by_employee_code(
            employee_code=manager_id,
            company_id=company_id,
        )

        if not manager:
            manager = await self.repository.find_by_id(
                employee_id=manager_id,
                company_id=company_id,
            )

        if not manager:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Manager not found: {manager_id}",
            )

        if not manager.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Manager is inactive: {manager_id}",
            )

        if employee_code and manager.get("employee_code") == employee_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Employee cannot be their own manager",
            )

        return manager

    async def _validate_unique_fields_for_create(
        self,
        email: str,
        phone: str,
        company_id: str,
    ) -> None:
        if await self.repository.exists_by_email(
            email=email,
            company_id=company_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email already in use: {email}",
            )

        if await self.repository.exists_by_phone(
            phone=phone,
            company_id=company_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Phone already in use: {phone}",
            )

    async def _validate_unique_fields_for_update(
        self,
        employee_id: str,
        update_data: Dict[str, Any],
        company_id: str,
    ) -> None:
        if "email" in update_data:
            if await self.repository.exists_by_email(
                email=update_data["email"],
                company_id=company_id,
                exclude_employee_id=employee_id,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Email already in use: {update_data['email']}",
                )

        if "phone" in update_data:
            if await self.repository.exists_by_phone(
                phone=update_data["phone"],
                company_id=company_id,
                exclude_employee_id=employee_id,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Phone already in use: {update_data['phone']}",
                )

    async def _get_probation_days(self, company_id: str = "default") -> int:
        settings = await self.company_settings_repository.find_by_company_id(
            company_id=company_id,
        )

        if not settings:
            return 90

        leave_policy = settings.get("leave_policy", {})
        return int(leave_policy.get("probation_period_days", 90))

    def _add_days_to_date(self, start_date: date, days: int) -> date:
        return start_date + timedelta(days=days)

    # -------------------------
    # Initialize balances
    # -------------------------

    async def _initialize_leave_balances(
        self,
        company_id: str = "default",
    ) -> List[Dict[str, Any]]:
        """
        Initialize leave balances from active leave types.
        """
        leave_types = await self.leave_type_repository.list_all(is_active=True)

        current_year = datetime.utcnow().year
        leave_balances: List[Dict[str, Any]] = []

        for leave_type in leave_types:
            default_grant = float(leave_type.get("default_annual_grant", 0.0) or 0.0)

            leave_balances.append(
                {
                    "leave_type_id": leave_type.get("id") or leave_type.get("_id"),
                    "leave_type_code": leave_type.get("code"),
                    "leave_type_name": leave_type.get("name"),
                    "granted": default_grant,
                    "used": 0.0,
                    "available": default_grant,
                    "carried_forward": 0.0,
                    "encashed": 0.0,
                    "year": current_year,
                }
            )

        return leave_balances

    async def _initialize_claim_limits(
        self,
        company_id: str = "default",
    ) -> List[Dict[str, Any]]:
        """
        Initialize claim limits from active claim types.
        """
        claim_types = await self.claim_type_repository.list_all(is_active=True)

        current_year = datetime.utcnow().year
        claim_limits: List[Dict[str, Any]] = []

        for claim_type in claim_types:
            annual_limit = float(claim_type.get("default_annual_limit", 0.0) or 0.0)
            monthly_limit = claim_type.get("default_monthly_limit")

            claim_limits.append(
                {
                    "claim_type_id": claim_type.get("id") or claim_type.get("_id"),
                    "claim_type_code": claim_type.get("code"),
                    "claim_type_name": claim_type.get("name"),
                    "annual_limit": annual_limit,
                    "monthly_limit": float(monthly_limit) if monthly_limit is not None else None,
                    "used": 0.0,
                    "available": annual_limit,
                    "year": current_year,
                }
            )

        return claim_limits

    # -------------------------
    # Create employee
    # -------------------------

    async def create_employee(
        self,
        request: CreateEmployeeRequest,
        created_by: Optional[str] = None,
    ) -> EmployeeCreatedResponse:
        """
        Create new employee with validation.
        """
        company_id = self._normalize_company_id(request.company_id)

        await self._validate_user_available(
            user_id=request.user_id,
            company_id=company_id,
        )

        await self._validate_department(request.department_id)

        await self._validate_designation(
            designation_id=request.designation_id,
            department_id=request.department_id,
        )

        await self._validate_manager(
            manager_id=request.manager_id,
            company_id=company_id,
        )

        await self._validate_unique_fields_for_create(
            email=str(request.email),
            phone=request.phone,
            company_id=company_id,
        )

        employee_code = await self.repository.generate_employee_code(
            prefix="EMP",
            company_id=company_id,
        )

        leave_balances = await self._initialize_leave_balances(company_id=company_id)
        claim_limits = await self._initialize_claim_limits(company_id=company_id)

        probation_end_date = request.probation_end_date

        if not probation_end_date:
            probation_days = await self._get_probation_days(company_id=company_id)
            probation_end_date = self._add_days_to_date(
                start_date=request.joining_date,
                days=probation_days,
            )

        employee_data = request.model_dump()
        employee_data["company_id"] = company_id
        employee_data["employee_code"] = employee_code
        employee_data["leave_balances"] = leave_balances
        employee_data["claim_limits"] = claim_limits
        employee_data["probation_end_date"] = probation_end_date
        employee_data["created_by"] = created_by
        employee_data["updated_by"] = created_by

        validated_data = self._validate_employee_payload(employee_data)

        try:
            employee_id = await self.repository.create(validated_data)

        except DuplicateKeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Employee already exists with duplicate employee_code, user_id, email, or phone",
            )

        employee = await self.repository.find_by_id(
            employee_id=employee_id,
            company_id=company_id,
        )

        enriched = await self._enrich_employee(employee) if employee else None

        return EmployeeCreatedResponse(
            message="Employee created successfully",
            employee_id=employee_id,
            employee_code=employee_code,
            employee=EmployeeResponse.model_validate(enriched) if enriched else None,
        )

    # -------------------------
    # Read operations
    # -------------------------

    async def get_employee(
        self,
        employee_id: str,
        company_id: str = "default",
        private: bool = False,
    ) -> EmployeeResponse | EmployeePrivateResponse:
        employee = await self._get_employee_or_404(
            employee_id=employee_id,
            company_id=company_id,
        )

        enriched = await self._enrich_employee(employee, private=private)

        if private:
            return EmployeePrivateResponse.model_validate(enriched)

        return EmployeeResponse.model_validate(enriched)

    async def get_employee_by_code(
        self,
        employee_code: str,
        company_id: str = "default",
        private: bool = False,
    ) -> EmployeeResponse | EmployeePrivateResponse:
        employee = await self._get_employee_by_code_or_404(
            employee_code=employee_code,
            company_id=company_id,
        )

        enriched = await self._enrich_employee(employee, private=private)

        if private:
            return EmployeePrivateResponse.model_validate(enriched)

        return EmployeeResponse.model_validate(enriched)

    async def get_employee_by_user_id(
        self,
        user_id: str,
        company_id: str = "default",
        private: bool = False,
    ) -> Optional[EmployeeResponse | EmployeePrivateResponse]:
        company_id = self._normalize_company_id(company_id)

        employee = await self.repository.find_by_user_id(
            user_id=user_id,
            company_id=company_id,
        )

        if not employee:
            return None

        enriched = await self._enrich_employee(employee, private=private)

        if private:
            return EmployeePrivateResponse.model_validate(enriched)

        return EmployeeResponse.model_validate(enriched)

    async def list_employees(
        self,
        params: EmployeeFilterParams,
    ) -> EmployeeListResponse:
        company_id = self._normalize_company_id(params.company_id)

        if params.search:
            employees = await self.repository.search(
                search_term=params.search,
                company_id=company_id,
                is_active=params.is_active,
                department_id=params.department_id,
                designation_id=params.designation_id,
                employment_status=params.employment_status.value if params.employment_status else None,
                skip=params.skip,
                limit=params.limit,
            )

            total = len(employees)

        else:
            employees = await self.repository.list_with_filters(
                company_id=company_id,
                department_id=params.department_id,
                designation_id=params.designation_id,
                manager_id=params.manager_id,
                employment_status=params.employment_status.value if params.employment_status else None,
                employee_type=params.employee_type.value if params.employee_type else None,
                work_location=params.work_location,
                work_mode=params.work_mode.value if params.work_mode else None,
                is_active=params.is_active,
                skip=params.skip,
                limit=params.limit,
                sort_by=params.sort_by,
                sort_order=params.sort_order,
            )

            total = await self.repository.count_all(
                company_id=company_id,
                is_active=params.is_active,
            )

        enriched_employees: List[EmployeeSummaryResponse] = []

        for employee in employees:
            enriched = await self._enrich_employee_summary(employee)
            enriched_employees.append(EmployeeSummaryResponse.model_validate(enriched))

        return EmployeeListResponse(
            employees=enriched_employees,
            total=total,
            skip=params.skip,
            limit=params.limit,
        )

    async def search_employees(
        self,
        params: EmployeeSearchParams,
    ) -> EmployeeListResponse:
        company_id = self._normalize_company_id(params.company_id)

        employees = await self.repository.search(
            search_term=params.query,
            company_id=company_id,
            is_active=params.is_active,
            department_id=params.department_id,
            designation_id=params.designation_id,
            employment_status=params.employment_status.value if params.employment_status else None,
            skip=params.skip,
            limit=params.limit,
        )

        enriched_employees: List[EmployeeSummaryResponse] = []

        for employee in employees:
            enriched = await self._enrich_employee_summary(employee)
            enriched_employees.append(EmployeeSummaryResponse.model_validate(enriched))

        return EmployeeListResponse(
            employees=enriched_employees,
            total=len(enriched_employees),
            skip=params.skip,
            limit=params.limit,
        )

    async def list_employees_for_dropdown(
        self,
        company_id: str = "default",
        is_active: Optional[bool] = True,
        department_id: Optional[str] = None,
    ) -> EmployeeDropdownListResponse:
        company_id = self._normalize_company_id(company_id)

        employees = await self.repository.list_for_dropdown(
            company_id=company_id,
            is_active=is_active,
            department_id=department_id,
            limit=1000,
        )

        enriched_employees: List[EmployeeDropdownResponse] = []

        for employee in employees:
            enriched = await self._enrich_employee_dropdown(employee)
            enriched_employees.append(EmployeeDropdownResponse.model_validate(enriched))

        return EmployeeDropdownListResponse(
            employees=enriched_employees,
            total=len(enriched_employees),
        )

    async def list_manager_options(
        self,
        company_id: str = "default",
        department_id: Optional[str] = None,
    ) -> EmployeeManagerListResponse:
        company_id = self._normalize_company_id(company_id)

        employees = await self.repository.list_for_dropdown(
            company_id=company_id,
            is_active=True,
            department_id=department_id,
            manager_only=True,
            limit=1000,
        )

        managers: List[EmployeeManagerOptionResponse] = []

        for employee in employees:
            enriched = await self._enrich_employee_dropdown(employee)
            managers.append(EmployeeManagerOptionResponse.model_validate(enriched))

        return EmployeeManagerListResponse(
            managers=managers,
            total=len(managers),
        )

    # -------------------------
    # Update operations
    # -------------------------

    async def update_employee(
        self,
        employee_id: str,
        request: UpdateEmployeeRequest,
        updated_by: Optional[str] = None,
        company_id: str = "default",
    ) -> EmployeeUpdatedResponse:
        company_id = self._normalize_company_id(company_id)

        employee = await self._get_employee_or_404(
            employee_id=employee_id,
            company_id=company_id,
        )

        update_data = request.model_dump(
            exclude_unset=True,
            exclude_none=False,
        )

        await self._validate_unique_fields_for_update(
            employee_id=employee_id,
            update_data=update_data,
            company_id=company_id,
        )

        final_department_id = update_data.get("department_id", employee.get("department_id"))
        final_designation_id = update_data.get("designation_id", employee.get("designation_id"))

        if "department_id" in update_data:
            await self._validate_department(update_data["department_id"])

        if "designation_id" in update_data:
            await self._validate_designation(
                designation_id=update_data["designation_id"],
                department_id=final_department_id,
            )

        if "manager_id" in update_data:
            await self._validate_manager(
                manager_id=update_data.get("manager_id"),
                employee_code=employee.get("employee_code"),
                company_id=company_id,
            )

        validation_payload = dict(employee)
        validation_payload.pop("_id", None)
        validation_payload.pop("id", None)
        validation_payload.update(update_data)
        validation_payload["updated_by"] = updated_by

        self._validate_employee_payload(validation_payload)

        update_data["updated_by"] = updated_by

        success = await self.repository.update(
            employee_id=employee_id,
            update_data=update_data,
            company_id=company_id,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update employee: {employee_id}",
            )

        updated_employee = await self._get_employee_or_404(
            employee_id=employee_id,
            company_id=company_id,
        )

        enriched = await self._enrich_employee(updated_employee)

        return EmployeeUpdatedResponse(
            message="Employee updated successfully",
            employee_code=employee.get("employee_code"),
            updated_at=datetime.utcnow(),
            employee=EmployeeResponse.model_validate(enriched),
        )

    async def update_employment_status(
        self,
        employee_id: str,
        request: UpdateEmploymentStatusRequest,
        updated_by: Optional[str] = None,
        company_id: str = "default",
    ) -> EmployeeStatusResponse:
        company_id = self._normalize_company_id(company_id)

        employee = await self._get_employee_or_404(
            employee_id=employee_id,
            company_id=company_id,
        )

        extra_fields: Dict[str, Any] = {}

        if request.employment_status == EmploymentStatus.ACTIVE:
            if request.confirmation_date:
                extra_fields["confirmation_date"] = request.confirmation_date

            extra_fields["is_active"] = True

        elif request.employment_status == EmploymentStatus.NOTICE_PERIOD:
            if not request.resignation_date:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="resignation_date is required for notice_period status",
                )

            extra_fields["resignation_date"] = request.resignation_date

            if request.last_working_date:
                extra_fields["last_working_date"] = request.last_working_date

            extra_fields["is_active"] = True

        elif request.employment_status in {
            EmploymentStatus.RESIGNED,
            EmploymentStatus.TERMINATED,
            EmploymentStatus.ABSCONDED,
            EmploymentStatus.RETIRED,
        }:
            extra_fields["is_active"] = False

            if request.resignation_date:
                extra_fields["resignation_date"] = request.resignation_date

            if request.last_working_date:
                extra_fields["last_working_date"] = request.last_working_date

        validation_payload = dict(employee)
        validation_payload.pop("_id", None)
        validation_payload.pop("id", None)
        validation_payload["employment_status"] = request.employment_status.value
        validation_payload.update(extra_fields)
        validation_payload["updated_by"] = updated_by

        self._validate_employee_payload(validation_payload)

        success = await self.repository.update_employment_status(
            employee_id=employee_id,
            status=request.employment_status.value,
            updated_by=updated_by,
            company_id=company_id,
            extra_fields=extra_fields,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update employment status: {employee_id}",
            )

        is_active = extra_fields.get("is_active", employee.get("is_active", True))

        return EmployeeStatusResponse(
            message="Employment status updated successfully",
            employee_code=employee.get("employee_code"),
            employment_status=request.employment_status,
            is_active=is_active,
        )

    async def update_manager(
        self,
        employee_id: str,
        request: UpdateManagerRequest,
        updated_by: Optional[str] = None,
        company_id: str = "default",
    ) -> EmployeeUpdatedResponse:
        company_id = self._normalize_company_id(company_id)

        employee = await self._get_employee_or_404(
            employee_id=employee_id,
            company_id=company_id,
        )

        await self._validate_manager(
            manager_id=request.manager_id,
            employee_code=employee.get("employee_code"),
            company_id=company_id,
        )

        success = await self.repository.update_manager(
            employee_id=employee_id,
            manager_id=request.manager_id,
            updated_by=updated_by,
            company_id=company_id,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update manager: {employee_id}",
            )

        updated_employee = await self._get_employee_or_404(
            employee_id=employee_id,
            company_id=company_id,
        )

        enriched = await self._enrich_employee(updated_employee)

        return EmployeeUpdatedResponse(
            message="Manager updated successfully",
            employee_code=employee.get("employee_code"),
            updated_at=datetime.utcnow(),
            employee=EmployeeResponse.model_validate(enriched),
        )

    async def update_bank_details(
        self,
        employee_id: str,
        request: UpdateBankDetailsRequest,
        updated_by: Optional[str] = None,
        company_id: str = "default",
    ) -> EmployeeUpdatedResponse:
        company_id = self._normalize_company_id(company_id)

        employee = await self._get_employee_or_404(
            employee_id=employee_id,
            company_id=company_id,
        )

        update_data = {
            "bank_details": request.bank_details.model_dump(),
            "updated_by": updated_by,
        }

        success = await self.repository.update(
            employee_id=employee_id,
            update_data=update_data,
            company_id=company_id,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update bank details: {employee_id}",
            )

        updated_employee = await self._get_employee_or_404(employee_id, company_id)
        enriched = await self._enrich_employee(updated_employee)

        return EmployeeUpdatedResponse(
            message="Bank details updated successfully",
            employee_code=employee.get("employee_code"),
            updated_at=datetime.utcnow(),
            employee=EmployeeResponse.model_validate(enriched),
        )

    async def update_emergency_contact(
        self,
        employee_id: str,
        request: UpdateEmergencyContactRequest,
        updated_by: Optional[str] = None,
        company_id: str = "default",
    ) -> EmployeeUpdatedResponse:
        company_id = self._normalize_company_id(company_id)

        employee = await self._get_employee_or_404(
            employee_id=employee_id,
            company_id=company_id,
        )

        update_data = {
            "emergency_contact": request.emergency_contact.model_dump(),
            "updated_by": updated_by,
        }

        success = await self.repository.update(
            employee_id=employee_id,
            update_data=update_data,
            company_id=company_id,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update emergency contact: {employee_id}",
            )

        updated_employee = await self._get_employee_or_404(employee_id, company_id)
        enriched = await self._enrich_employee(updated_employee)

        return EmployeeUpdatedResponse(
            message="Emergency contact updated successfully",
            employee_code=employee.get("employee_code"),
            updated_at=datetime.utcnow(),
            employee=EmployeeResponse.model_validate(enriched),
        )

    async def update_addresses(
        self,
        employee_id: str,
        request: UpdateEmployeeAddressRequest,
        updated_by: Optional[str] = None,
        company_id: str = "default",
    ) -> EmployeeUpdatedResponse:
        company_id = self._normalize_company_id(company_id)

        employee = await self._get_employee_or_404(
            employee_id=employee_id,
            company_id=company_id,
        )

        update_data = request.model_dump(exclude_unset=True, exclude_none=False)
        update_data["updated_by"] = updated_by

        validation_payload = dict(employee)
        validation_payload.pop("_id", None)
        validation_payload.pop("id", None)
        validation_payload.update(update_data)

        self._validate_employee_payload(validation_payload)

        success = await self.repository.update(
            employee_id=employee_id,
            update_data=update_data,
            company_id=company_id,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update employee address: {employee_id}",
            )

        updated_employee = await self._get_employee_or_404(employee_id, company_id)
        enriched = await self._enrich_employee(updated_employee)

        return EmployeeUpdatedResponse(
            message="Employee address updated successfully",
            employee_code=employee.get("employee_code"),
            updated_at=datetime.utcnow(),
            employee=EmployeeResponse.model_validate(enriched),
        )

    async def update_leave_balances(
        self,
        employee_id: str,
        request: UpdateLeaveBalancesRequest,
        updated_by: Optional[str] = None,
        company_id: str = "default",
    ) -> EmployeeUpdatedResponse:
        company_id = self._normalize_company_id(company_id)

        employee = await self._get_employee_or_404(employee_id, company_id)

        success = await self.repository.update_leave_balances(
            employee_id=employee_id,
            leave_balances=[
                balance.model_dump() for balance in request.leave_balances
            ],
            updated_by=updated_by,
            company_id=company_id,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update leave balances: {employee_id}",
            )

        updated_employee = await self._get_employee_or_404(employee_id, company_id)
        enriched = await self._enrich_employee(updated_employee)

        return EmployeeUpdatedResponse(
            message="Leave balances updated successfully",
            employee_code=employee.get("employee_code"),
            updated_at=datetime.utcnow(),
            employee=EmployeeResponse.model_validate(enriched),
        )

    async def update_claim_limits(
        self,
        employee_id: str,
        request: UpdateClaimLimitsRequest,
        updated_by: Optional[str] = None,
        company_id: str = "default",
    ) -> EmployeeUpdatedResponse:
        company_id = self._normalize_company_id(company_id)

        employee = await self._get_employee_or_404(employee_id, company_id)

        success = await self.repository.update_claim_limits(
            employee_id=employee_id,
            claim_limits=[
                claim_limit.model_dump() for claim_limit in request.claim_limits
            ],
            updated_by=updated_by,
            company_id=company_id,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update claim limits: {employee_id}",
            )

        updated_employee = await self._get_employee_or_404(employee_id, company_id)
        enriched = await self._enrich_employee(updated_employee)

        return EmployeeUpdatedResponse(
            message="Claim limits updated successfully",
            employee_code=employee.get("employee_code"),
            updated_at=datetime.utcnow(),
            employee=EmployeeResponse.model_validate(enriched),
        )

    # -------------------------
    # Activate / Deactivate
    # -------------------------

    async def deactivate_employee(
        self,
        employee_id: str,
        updated_by: Optional[str] = None,
        company_id: str = "default",
        employment_status: str = "terminated",
    ) -> EmployeeStatusResponse:
        company_id = self._normalize_company_id(company_id)

        employee = await self._get_employee_or_404(
            employee_id=employee_id,
            company_id=company_id,
        )

        if not employee.get("is_active", False):
            return EmployeeStatusResponse(
                message="Employee is already inactive",
                employee_code=employee.get("employee_code"),
                employment_status=EmploymentStatus(employee.get("employment_status")),
                is_active=False,
            )

        success = await self.repository.deactivate(
            employee_id=employee_id,
            updated_by=updated_by,
            company_id=company_id,
            employment_status=employment_status,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to deactivate employee: {employee_id}",
            )

        return EmployeeStatusResponse(
            message="Employee deactivated successfully",
            employee_code=employee.get("employee_code"),
            employment_status=EmploymentStatus(employment_status),
            is_active=False,
        )

    async def activate_employee(
        self,
        employee_id: str,
        updated_by: Optional[str] = None,
        company_id: str = "default",
    ) -> EmployeeStatusResponse:
        company_id = self._normalize_company_id(company_id)

        employee = await self._get_employee_or_404(
            employee_id=employee_id,
            company_id=company_id,
        )

        if employee.get("is_active", False):
            return EmployeeStatusResponse(
                message="Employee is already active",
                employee_code=employee.get("employee_code"),
                employment_status=EmploymentStatus(employee.get("employment_status")),
                is_active=True,
            )

        success = await self.repository.activate(
            employee_id=employee_id,
            updated_by=updated_by,
            company_id=company_id,
            employment_status="active",
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to activate employee: {employee_id}",
            )

        return EmployeeStatusResponse(
            message="Employee activated successfully",
            employee_code=employee.get("employee_code"),
            employment_status=EmploymentStatus.ACTIVE,
            is_active=True,
        )

    # -------------------------
    # Statistics
    # -------------------------

    async def get_statistics(
        self,
        company_id: str = "default",
    ) -> EmployeeStatisticsResponse:
        company_id = self._normalize_company_id(company_id)

        stats = await self.repository.get_statistics(company_id=company_id)
        return EmployeeStatisticsResponse.model_validate(stats)

    async def get_department_statistics(
        self,
        company_id: str = "default",
    ) -> EmployeeDepartmentStatisticsResponse:
        company_id = self._normalize_company_id(company_id)

        raw_stats = await self.repository.get_department_statistics(
            company_id=company_id,
            is_active=True,
        )

        departments: List[EmployeeDepartmentStatisticsItem] = []

        for item in raw_stats:
            department_id = item.get("_id")
            department_name = None

            if department_id:
                department = await self.department_repository.find_by_id(department_id)
                if department:
                    department_name = department.get("name")

            departments.append(
                EmployeeDepartmentStatisticsItem(
                    department_id=department_id,
                    department_name=department_name,
                    count=item.get("count", 0),
                )
            )

        return EmployeeDepartmentStatisticsResponse(
            company_id=company_id,
            departments=departments,
        )

    async def get_status_statistics(
        self,
        company_id: str = "default",
    ) -> EmployeeStatusStatisticsResponse:
        company_id = self._normalize_company_id(company_id)

        raw_stats = await self.repository.get_status_statistics(company_id=company_id)

        statuses = [
            EmployeeStatusStatisticsItem(
                employment_status=item.get("_id") or "unknown",
                count=item.get("count", 0),
            )
            for item in raw_stats
        ]

        return EmployeeStatusStatisticsResponse(
            company_id=company_id,
            statuses=statuses,
        )

    # -------------------------
    # Data enrichment helpers
    # -------------------------

    async def _enrich_employee(
        self,
        employee: Dict[str, Any],
        private: bool = False,
    ) -> Dict[str, Any]:
        enriched = dict(employee)

        enriched["full_name"] = self._full_name(enriched)
        enriched["bank_details_available"] = bool(enriched.get("bank_details"))

        department_id = enriched.get("department_id")

        if department_id:
            department = await self.department_repository.find_by_id(department_id)

            if department:
                enriched["department_name"] = department.get("name")
                enriched["department_code"] = department.get("code")

        designation_id = enriched.get("designation_id")

        if designation_id:
            designation = await self.designation_repository.find_by_id(designation_id)

            if designation:
                enriched["designation_name"] = designation.get("name")
                enriched["designation_code"] = designation.get("code")

        manager_id = enriched.get("manager_id")

        if manager_id:
            manager = await self.repository.find_by_employee_code(
                employee_code=manager_id,
                company_id=enriched.get("company_id", "default"),
            )

            if not manager:
                manager = await self.repository.find_by_id(
                    employee_id=manager_id,
                    company_id=enriched.get("company_id", "default"),
                )

            if manager:
                enriched["manager_name"] = self._full_name(manager)
                enriched["manager_employee_code"] = manager.get("employee_code")

        if not private:
            enriched["pan_number"] = self._mask_value(enriched.get("pan_number"))
            enriched["aadhaar_number"] = self._mask_value(enriched.get("aadhaar_number"))
            enriched.pop("passport_number", None)
            enriched.pop("driving_license", None)
            enriched.pop("bank_details", None)

        return enriched

    async def _enrich_employee_summary(
        self,
        employee: Dict[str, Any],
    ) -> Dict[str, Any]:
        enriched = dict(employee)

        enriched["full_name"] = self._full_name(enriched)

        department_id = enriched.get("department_id")

        if department_id:
            department = await self.department_repository.find_by_id(department_id)

            if department:
                enriched["department_name"] = department.get("name")
                enriched["department_code"] = department.get("code")

        designation_id = enriched.get("designation_id")

        if designation_id:
            designation = await self.designation_repository.find_by_id(designation_id)

            if designation:
                enriched["designation_name"] = designation.get("name")
                enriched["designation_code"] = designation.get("code")

        manager_id = enriched.get("manager_id")

        if manager_id:
            manager = await self.repository.find_by_employee_code(
                employee_code=manager_id,
                company_id=enriched.get("company_id", "default"),
            )

            if manager:
                enriched["manager_name"] = self._full_name(manager)

        return enriched

    async def _enrich_employee_dropdown(
        self,
        employee: Dict[str, Any],
    ) -> Dict[str, Any]:
        enriched = dict(employee)

        enriched["full_name"] = self._full_name(enriched)

        department_id = enriched.get("department_id")

        if department_id:
            department = await self.department_repository.find_by_id(department_id)

            if department:
                enriched["department_name"] = department.get("name")

        designation_id = enriched.get("designation_id")

        if designation_id:
            designation = await self.designation_repository.find_by_id(designation_id)

            if designation:
                enriched["designation_name"] = designation.get("name")

        return enriched