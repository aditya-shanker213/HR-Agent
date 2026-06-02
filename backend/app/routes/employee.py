"""
Employee API routes.

Final paths depend on how main.py mounts routers.

Recommended:
    app.include_router(employee.router, prefix=settings.API_PREFIX)

Then final paths become:
    /api/v1/employees

Pattern:
Route → Service → Repository → MongoDB

Routes handle:
- HTTP request/response
- Auth dependencies
- Permission checks
- Query/body parameters

Business logic stays in:
    employee_service.py
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.app.database.mongo_connection import get_database
from backend.app.dependencies.auth_dependencies import get_current_active_user
from backend.app.schemas.employee_schema import (
    CreateEmployeeRequest,
    EmployeeCreatedResponse,
    EmployeeDepartmentStatisticsResponse,
    EmployeeDropdownListResponse,
    EmployeeFilterParams,
    EmployeeListResponse,
    EmployeeManagerListResponse,
    EmployeePrivateResponse,
    EmployeeResponse,
    EmployeeSearchParams,
    EmployeeStatisticsResponse,
    EmployeeStatusResponse,
    EmployeeStatusStatisticsResponse,
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
from backend.app.services.employee_service import EmployeeService


router = APIRouter(prefix="/employees", tags=["Employees"])


# -------------------------
# Dependency injection
# -------------------------


async def get_employee_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> EmployeeService:
    """
    Create EmployeeService instance.
    """
    return EmployeeService(db)


# -------------------------
# Auth helpers
# -------------------------


def _get_value(user: Any, key: str, default: Any = None) -> Any:
    """
    Read value from dict or Pydantic/object current_user.
    """
    if isinstance(user, dict):
        return user.get(key, default)

    return getattr(user, key, default)


def get_actor_id(current_user: Any) -> str:
    """
    Extract logged-in user's ID.
    """
    actor_id = (
        _get_value(current_user, "id")
        or _get_value(current_user, "_id")
        or _get_value(current_user, "user_id")
        or _get_value(current_user, "username")
        or "system"
    )

    return str(actor_id)


def get_actor_role(current_user: Any) -> str:
    """
    Extract logged-in user's role.
    """
    role = _get_value(current_user, "role", "")

    if hasattr(role, "value"):
        role = role.value

    return str(role).strip().lower()


def require_roles(current_user: Any, allowed_roles: set[str]) -> None:
    """
    Local role guard.

    This avoids dependency-name mismatch problems like:
    - require_admin
    - require_admin_user
    - require_hr_or_admin_user

    Your auth dependency only needs to provide current active user with role.
    """
    role = get_actor_role(current_user)

    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action",
        )


def require_hr_or_admin(current_user: Any) -> None:
    require_roles(current_user, {"hr", "admin"})


def require_admin(current_user: Any) -> None:
    require_roles(current_user, {"admin"})


async def ensure_self_or_hr_admin(
    employee_id: str,
    current_user: Any,
    service: EmployeeService,
    company_id: str = "default",
) -> None:
    """
    Allow:
    - HR/Admin to access any employee
    - Employee to access only their own employee profile
    """
    role = get_actor_role(current_user)

    if role in {"hr", "admin"}:
        return

    actor_id = get_actor_id(current_user)

    employee = await service.get_employee_by_user_id(
        user_id=actor_id,
        company_id=company_id,
        private=False,
    )

    if not employee or employee.id != employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own employee information",
        )


# -------------------------
# Create employee
# -------------------------


@router.post(
    "",
    response_model=EmployeeCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create employee",
    description="Create a new employee profile. HR/Admin only.",
)
async def create_employee(
    request: CreateEmployeeRequest,
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
):
    """
    Create new employee.

    Automatically:
    - Generates employee code
    - Initializes leave balances
    - Initializes claim limits
    - Calculates probation end date from company settings
    """
    require_hr_or_admin(current_user)

    try:
        return await service.create_employee(
            request=request,
            created_by=get_actor_id(current_user),
        )

    except HTTPException:
        raise


# -------------------------
# Read routes
# Important:
# Static routes must stay before /{employee_id}
# -------------------------


@router.get(
    "",
    response_model=EmployeeListResponse,
    status_code=status.HTTP_200_OK,
    summary="List employees",
    description="List employees with filters, search, sorting, and pagination.",
)
async def list_employees(
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
    department_id: Optional[str] = Query(default=None, description="Filter by department"),
    designation_id: Optional[str] = Query(default=None, description="Filter by designation"),
    manager_id: Optional[str] = Query(default=None, description="Filter by manager"),
    work_location: Optional[str] = Query(default=None, description="Filter by work location"),
    work_mode: Optional[str] = Query(default=None, description="Filter by work mode"),
    employment_status: Optional[str] = Query(default=None, description="Filter by employment status"),
    employee_type: Optional[str] = Query(default=None, description="Filter by employee type"),
    is_active: Optional[bool] = Query(default=True, description="Filter by active status"),
    search: Optional[str] = Query(default=None, max_length=100, description="Search by name, code, email, phone"),
    skip: int = Query(default=0, ge=0, description="Records to skip"),
    limit: int = Query(default=100, ge=1, le=500, description="Records to return"),
    sort_by: str = Query(default="employee_code", description="Sort field"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$", description="Sort order"),
):
    """
    List employees.

    Available to all authenticated users.
    """
    params = EmployeeFilterParams(
        company_id=company_id,
        department_id=department_id,
        designation_id=designation_id,
        manager_id=manager_id,
        work_location=work_location,
        work_mode=work_mode,
        employment_status=employment_status,
        employee_type=employee_type,
        is_active=is_active,
        search=search,
        skip=skip,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    try:
        return await service.list_employees(params)

    except HTTPException:
        raise


@router.get(
    "/search",
    response_model=EmployeeListResponse,
    status_code=status.HTTP_200_OK,
    summary="Search employees",
    description="Search employees by name, employee code, email, personal email, or phone.",
)
async def search_employees(
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    query: str = Query(..., min_length=1, max_length=100, description="Search query"),
    company_id: str = Query(default="default", description="Company identifier"),
    department_id: Optional[str] = Query(default=None),
    designation_id: Optional[str] = Query(default=None),
    employment_status: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=True),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    """
    Search employees.
    """
    params = EmployeeSearchParams(
        company_id=company_id,
        query=query,
        department_id=department_id,
        designation_id=designation_id,
        employment_status=employment_status,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )

    try:
        return await service.search_employees(params)

    except HTTPException:
        raise


@router.get(
    "/dropdown",
    response_model=EmployeeDropdownListResponse,
    status_code=status.HTTP_200_OK,
    summary="Employee dropdown",
    description="Get employees for dropdown/select options.",
)
async def get_employees_dropdown(
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
    is_active: Optional[bool] = Query(default=True, description="Filter by active status"),
    department_id: Optional[str] = Query(default=None, description="Filter by department"),
):
    """
    Get employee dropdown list.
    """
    try:
        return await service.list_employees_for_dropdown(
            company_id=company_id,
            is_active=is_active,
            department_id=department_id,
        )

    except HTTPException:
        raise


@router.get(
    "/managers",
    response_model=EmployeeManagerListResponse,
    status_code=status.HTTP_200_OK,
    summary="Manager options",
    description="Get active employee options for reporting manager dropdown.",
)
async def get_manager_options(
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
    department_id: Optional[str] = Query(default=None, description="Filter by department"),
):
    """
    Get manager dropdown options.
    """
    try:
        return await service.list_manager_options(
            company_id=company_id,
            department_id=department_id,
        )

    except HTTPException:
        raise


@router.get(
    "/statistics",
    response_model=EmployeeStatisticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Employee statistics",
    description="Get employee statistics. HR/Admin only.",
)
async def get_employee_statistics(
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Get employee statistics.
    """
    require_hr_or_admin(current_user)

    try:
        return await service.get_statistics(company_id=company_id)

    except HTTPException:
        raise


@router.get(
    "/statistics/departments",
    response_model=EmployeeDepartmentStatisticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Department-wise employee statistics",
    description="Get employee count grouped by department. HR/Admin only.",
)
async def get_department_statistics(
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Get department-wise employee statistics.
    """
    require_hr_or_admin(current_user)

    try:
        return await service.get_department_statistics(company_id=company_id)

    except HTTPException:
        raise


@router.get(
    "/statistics/statuses",
    response_model=EmployeeStatusStatisticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Status-wise employee statistics",
    description="Get employee count grouped by employment status. HR/Admin only.",
)
async def get_status_statistics(
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Get status-wise employee statistics.
    """
    require_hr_or_admin(current_user)

    try:
        return await service.get_status_statistics(company_id=company_id)

    except HTTPException:
        raise


@router.get(
    "/code/{employee_code}",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get employee by code",
    description="Get employee profile by employee code.",
)
async def get_employee_by_code(
    employee_code: str = Path(..., description="Employee code"),
    current_user: Annotated[Any, Depends(get_current_active_user)] = None,
    service: Annotated[EmployeeService, Depends(get_employee_service)] = None,
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Get employee by employee code.
    """
    try:
        return await service.get_employee_by_code(
            employee_code=employee_code,
            company_id=company_id,
            private=False,
        )

    except HTTPException:
        raise


@router.get(
    "/user/{user_id}",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get employee by user ID",
    description="Get employee profile by user ID.",
)
async def get_employee_by_user_id(
    user_id: str = Path(..., description="User ID"),
    current_user: Annotated[Any, Depends(get_current_active_user)] = None,
    service: Annotated[EmployeeService, Depends(get_employee_service)] = None,
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Get employee by user_id.

    HR/Admin can query any user.
    Normal employee should only query self.
    """
    role = get_actor_role(current_user)
    actor_id = get_actor_id(current_user)

    if role not in {"hr", "admin"} and user_id != actor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own employee profile",
        )

    try:
        employee = await service.get_employee_by_user_id(
            user_id=user_id,
            company_id=company_id,
            private=False,
        )

        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Employee not found for user: {user_id}",
            )

        return employee

    except HTTPException:
        raise


@router.get(
    "/{employee_id}/private",
    response_model=EmployeePrivateResponse,
    status_code=status.HTTP_200_OK,
    summary="Get private employee profile",
    description="Get private employee profile including sensitive details. HR/Admin only.",
)
async def get_private_employee(
    employee_id: str = Path(..., description="Employee ID"),
    current_user: Annotated[Any, Depends(get_current_active_user)] = None,
    service: Annotated[EmployeeService, Depends(get_employee_service)] = None,
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Get private employee profile.

    HR/Admin only.
    """
    require_hr_or_admin(current_user)

    try:
        return await service.get_employee(
            employee_id=employee_id,
            company_id=company_id,
            private=True,
        )

    except HTTPException:
        raise


@router.get(
    "/{employee_id}",
    response_model=EmployeeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get employee by ID",
    description="Get employee profile by ID.",
)
async def get_employee(
    employee_id: str = Path(..., description="Employee ID"),
    current_user: Annotated[Any, Depends(get_current_active_user)] = None,
    service: Annotated[EmployeeService, Depends(get_employee_service)] = None,
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Get employee by ID.

    Normal response masks sensitive document values and does not expose bank details.
    """
    try:
        return await service.get_employee(
            employee_id=employee_id,
            company_id=company_id,
            private=False,
        )

    except HTTPException:
        raise


# -------------------------
# Update routes
# -------------------------


@router.put(
    "/{employee_id}",
    response_model=EmployeeUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update employee",
    description="Update employee profile. HR/Admin only.",
)
async def update_employee(
    employee_id: str,
    request: UpdateEmployeeRequest,
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Update employee profile.

    HR/Admin only.
    """
    require_hr_or_admin(current_user)

    try:
        return await service.update_employee(
            employee_id=employee_id,
            request=request,
            updated_by=get_actor_id(current_user),
            company_id=company_id,
        )

    except HTTPException:
        raise


@router.patch(
    "/{employee_id}/status",
    response_model=EmployeeStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Update employment status",
    description="Update employment status. HR/Admin only.",
)
async def update_employment_status(
    employee_id: str,
    request: UpdateEmploymentStatusRequest,
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Update employment status.
    """
    require_hr_or_admin(current_user)

    try:
        return await service.update_employment_status(
            employee_id=employee_id,
            request=request,
            updated_by=get_actor_id(current_user),
            company_id=company_id,
        )

    except HTTPException:
        raise


@router.patch(
    "/{employee_id}/manager",
    response_model=EmployeeUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update employee manager",
    description="Update employee reporting manager. HR/Admin only.",
)
async def update_manager(
    employee_id: str,
    request: UpdateManagerRequest,
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Update reporting manager.
    """
    require_hr_or_admin(current_user)

    try:
        return await service.update_manager(
            employee_id=employee_id,
            request=request,
            updated_by=get_actor_id(current_user),
            company_id=company_id,
        )

    except HTTPException:
        raise


@router.put(
    "/{employee_id}/bank",
    response_model=EmployeeUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update bank details",
    description="Update bank details. Employee can update own profile. HR/Admin can update any profile.",
)
async def update_bank_details(
    employee_id: str,
    request: UpdateBankDetailsRequest,
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Update bank details.

    Allowed:
    - Employee updating own bank details
    - HR/Admin updating any employee
    """
    await ensure_self_or_hr_admin(
        employee_id=employee_id,
        current_user=current_user,
        service=service,
        company_id=company_id,
    )

    try:
        return await service.update_bank_details(
            employee_id=employee_id,
            request=request,
            updated_by=get_actor_id(current_user),
            company_id=company_id,
        )

    except HTTPException:
        raise


@router.put(
    "/{employee_id}/emergency",
    response_model=EmployeeUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update emergency contact",
    description="Update emergency contact. Employee can update own profile. HR/Admin can update any profile.",
)
async def update_emergency_contact(
    employee_id: str,
    request: UpdateEmergencyContactRequest,
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Update emergency contact.

    Allowed:
    - Employee updating own emergency contact
    - HR/Admin updating any employee
    """
    await ensure_self_or_hr_admin(
        employee_id=employee_id,
        current_user=current_user,
        service=service,
        company_id=company_id,
    )

    try:
        return await service.update_emergency_contact(
            employee_id=employee_id,
            request=request,
            updated_by=get_actor_id(current_user),
            company_id=company_id,
        )

    except HTTPException:
        raise


@router.put(
    "/{employee_id}/address",
    response_model=EmployeeUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update employee address",
    description="Update current/permanent address. Employee can update own profile. HR/Admin can update any profile.",
)
async def update_employee_address(
    employee_id: str,
    request: UpdateEmployeeAddressRequest,
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Update employee address.
    """
    await ensure_self_or_hr_admin(
        employee_id=employee_id,
        current_user=current_user,
        service=service,
        company_id=company_id,
    )

    try:
        return await service.update_addresses(
            employee_id=employee_id,
            request=request,
            updated_by=get_actor_id(current_user),
            company_id=company_id,
        )

    except HTTPException:
        raise


@router.put(
    "/{employee_id}/leave-balances",
    response_model=EmployeeUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update employee leave balances",
    description="Replace employee leave balances. HR/Admin only.",
)
async def update_leave_balances(
    employee_id: str,
    request: UpdateLeaveBalancesRequest,
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Replace leave balances.

    HR/Admin only.
    """
    require_hr_or_admin(current_user)

    try:
        return await service.update_leave_balances(
            employee_id=employee_id,
            request=request,
            updated_by=get_actor_id(current_user),
            company_id=company_id,
        )

    except HTTPException:
        raise


@router.put(
    "/{employee_id}/claim-limits",
    response_model=EmployeeUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update employee claim limits",
    description="Replace employee claim limits. HR/Admin only.",
)
async def update_claim_limits(
    employee_id: str,
    request: UpdateClaimLimitsRequest,
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Replace claim limits.

    HR/Admin only.
    """
    require_hr_or_admin(current_user)

    try:
        return await service.update_claim_limits(
            employee_id=employee_id,
            request=request,
            updated_by=get_actor_id(current_user),
            company_id=company_id,
        )

    except HTTPException:
        raise


# -------------------------
# Activate / deactivate
# -------------------------


@router.post(
    "/{employee_id}/deactivate",
    response_model=EmployeeStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate employee",
    description="Deactivate employee using soft delete. Admin only.",
)
async def deactivate_employee(
    employee_id: str,
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
    employment_status: str = Query(default="terminated", description="Exit status to set"),
):
    """
    Deactivate employee.

    Admin only.
    """
    require_admin(current_user)

    try:
        return await service.deactivate_employee(
            employee_id=employee_id,
            updated_by=get_actor_id(current_user),
            company_id=company_id,
            employment_status=employment_status,
        )

    except HTTPException:
        raise


@router.post(
    "/{employee_id}/activate",
    response_model=EmployeeStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate employee",
    description="Reactivate employee. Admin only.",
)
async def activate_employee(
    employee_id: str,
    current_user: Annotated[Any, Depends(get_current_active_user)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Reactivate employee.

    Admin only.
    """
    require_admin(current_user)

    try:
        return await service.activate_employee(
            employee_id=employee_id,
            updated_by=get_actor_id(current_user),
            company_id=company_id,
        )

    except HTTPException:
        raise