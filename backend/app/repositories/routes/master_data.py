"""
Master Data routes.

All master data endpoints for:
- Departments
- Designations
- Leave Types
- Claim Types
- Holidays

Pattern:
Route -> Master Data Service -> Repository -> MongoDB

Access Control:
- Authenticated users can read master data for dropdowns
- HR/Admin can create, update, deactivate, activate
- Admin only can bulk import
"""

from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.app.database.mongo_connection import get_database
from backend.app.dependencies.auth_dependencies import (
    get_current_active_user,
    require_admin,
    require_hr,
)
from backend.app.repositories.claim_type_repository import ClaimTypeRepository
from backend.app.repositories.department_repository import DepartmentRepository
from backend.app.repositories.designation_repository import DesignationRepository
from backend.app.repositories.holiday_repository import HolidayRepository
from backend.app.repositories.leave_type_repository import LeaveTypeRepository
from backend.app.repositories.user_repository import UserRepository
from backend.app.schemas.master_data_schema import (
    BulkClaimTypeImportRequest,
    BulkClaimTypeImportResponse,
    BulkDepartmentImportRequest,
    BulkDepartmentImportResponse,
    BulkDesignationImportRequest,
    BulkDesignationImportResponse,
    BulkHolidayImportRequest,
    BulkHolidayImportResponse,
    BulkLeaveTypeImportRequest,
    BulkLeaveTypeImportResponse,
    ClaimTypeCreatedResponse,
    ClaimTypeDeactivatedResponse,
    ClaimTypeDetailResponse,
    ClaimTypeDropdownResponse,
    ClaimTypeListResponse,
    ClaimTypeStatisticsResponse,
    ClaimTypeUpdatedResponse,
    CreateClaimTypeRequest,
    CreateDepartmentRequest,
    CreateDesignationRequest,
    CreateHolidayRequest,
    CreateLeaveTypeRequest,
    DepartmentCreatedResponse,
    DepartmentDeactivatedResponse,
    DepartmentDetailResponse,
    DepartmentListResponse,
    DepartmentUpdatedResponse,
    DesignationCreatedResponse,
    DesignationDeactivatedResponse,
    DesignationDetailResponse,
    DesignationDropdownResponse,
    DesignationListResponse,
    DesignationUpdatedResponse,
    HolidayCalendarResponse,
    HolidayCreatedResponse,
    HolidayDeactivatedResponse,
    HolidayDetailResponse,
    HolidayDropdownResponse,
    HolidayListResponse,
    HolidayStatisticsResponse,
    HolidayUpdatedResponse,
    LeaveTypeCreatedResponse,
    LeaveTypeDeactivatedResponse,
    LeaveTypeDetailResponse,
    LeaveTypeDropdownResponse,
    LeaveTypeListResponse,
    LeaveTypeStatisticsResponse,
    LeaveTypeUpdatedResponse,
    UpdateClaimTypeRequest,
    UpdateDepartmentRequest,
    UpdateDesignationRequest,
    UpdateHolidayRequest,
    UpdateLeaveTypeRequest,
)
from backend.app.services.master_data_service import MasterDataService


router = APIRouter(prefix="/master-data", tags=["Master Data"])


# -------------------------
# Dependency injection
# -------------------------


async def get_master_data_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> MasterDataService:
    """
    Create MasterDataService instance with all dependencies.
    """

    department_repo = DepartmentRepository(db)
    designation_repo = DesignationRepository(db)
    leave_type_repo = LeaveTypeRepository(db)
    claim_type_repo = ClaimTypeRepository(db)
    holiday_repo = HolidayRepository(db)
    user_repo = UserRepository(db)

    return MasterDataService(
        department_repo=department_repo,
        designation_repo=designation_repo,
        leave_type_repo=leave_type_repo,
        claim_type_repo=claim_type_repo,
        holiday_repo=holiday_repo,
        user_repo=user_repo,
    )


def get_actor_id(current_user: dict) -> str:
    """
    Extract logged-in user's ID from current_user.
    """

    actor_id = current_user.get("id") or current_user.get("_id")

    if not actor_id:
        actor_id = current_user.get("username", "system")

    return str(actor_id)


# -------------------------
# Department Routes
# -------------------------


@router.post(
    "/departments",
    response_model=DepartmentCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new department",
)
async def create_department(
    request: CreateDepartmentRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    created_by = get_actor_id(current_user)

    department = await service.create_department(
        department_data=request.model_dump(exclude_none=True),
        created_by=created_by,
    )

    return DepartmentCreatedResponse(
        message="Department created successfully",
        department_id=department.get("id") or department.get("_id"),
        department=DepartmentListResponse(**department),
    )


@router.get(
    "/departments",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="List departments",
)
async def list_departments(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    is_active: Optional[bool] = Query(None),
    location: Optional[str] = Query(None),
    parent_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None, min_length=2, max_length=100),
    sort_by: str = Query(
        "display_order",
        pattern="^(display_order|name|code|created_at|updated_at)$",
    ),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    departments, total_count = await service.list_departments(
        is_active=is_active,
        location=location,
        parent_id=parent_id,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )

    return {
        "departments": [
            DepartmentListResponse(**department)
            for department in departments
        ],
        "total": total_count,
        "skip": skip,
        "limit": limit,
    }


@router.get(
    "/departments/statistics",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Get department statistics",
)
async def get_department_statistics(
    _current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    return await service.get_department_statistics()


@router.post(
    "/departments/bulk-import",
    response_model=BulkDepartmentImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk import departments",
)
async def bulk_import_departments(
    request: BulkDepartmentImportRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    created_by = get_actor_id(current_user)

    departments_data = [
        department.model_dump(exclude_none=True)
        for department in request.departments
    ]

    result = await service.bulk_import_departments(
        departments=departments_data,
        created_by=created_by,
        skip_duplicates=request.skip_duplicates,
    )

    return BulkDepartmentImportResponse(**result)


@router.get(
    "/departments/{department_id}",
    response_model=DepartmentDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get department by ID",
)
async def get_department(
    department_id: str,
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    department = await service.get_department_by_id(
        department_id=department_id,
        include_details=True,
    )

    return DepartmentDetailResponse(**department)


@router.patch(
    "/departments/{department_id}",
    response_model=DepartmentUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update department",
)
async def update_department(
    department_id: str,
    request: UpdateDepartmentRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    department = await service.update_department(
        department_id=department_id,
        update_data=request.model_dump(exclude_none=True),
        updated_by=updated_by,
    )

    return DepartmentUpdatedResponse(
        message="Department updated successfully",
        department=DepartmentListResponse(**department),
    )


@router.delete(
    "/departments/{department_id}",
    response_model=DepartmentDeactivatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate department",
)
async def deactivate_department(
    department_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    await service.deactivate_department(
        department_id=department_id,
        updated_by=updated_by,
    )

    return DepartmentDeactivatedResponse(
        message="Department deactivated successfully",
        department_id=department_id,
    )


@router.patch(
    "/departments/{department_id}/activate",
    response_model=DepartmentUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Reactivate department",
)
async def activate_department(
    department_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    department = await service.activate_department(
        department_id=department_id,
        updated_by=updated_by,
    )

    return DepartmentUpdatedResponse(
        message="Department activated successfully",
        department=DepartmentListResponse(**department),
    )


# -------------------------
# Designation Routes
# -------------------------


@router.post(
    "/designations",
    response_model=DesignationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new designation",
)
async def create_designation(
    request: CreateDesignationRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    created_by = get_actor_id(current_user)

    designation = await service.create_designation(
        designation_data=request.model_dump(exclude_none=True),
        created_by=created_by,
    )

    return DesignationCreatedResponse(
        message="Designation created successfully",
        designation_id=designation.get("id") or designation.get("_id"),
        designation=DesignationListResponse(**designation),
    )


@router.get(
    "/designations",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="List designations",
)
async def list_designations(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    is_active: Optional[bool] = Query(None),
    department_id: Optional[str] = Query(None),
    level: Optional[int] = Query(None, ge=1, le=10),
    search: Optional[str] = Query(None, min_length=2, max_length=100),
    sort_by: str = Query(
        "display_order",
        pattern="^(display_order|name|code|level|department_id|created_at|updated_at)$",
    ),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    designations, total_count = await service.list_designations(
        is_active=is_active,
        department_id=department_id,
        level=level,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )

    return {
        "designations": [
            DesignationListResponse(**designation)
            for designation in designations
        ],
        "total": total_count,
        "skip": skip,
        "limit": limit,
    }


@router.get(
    "/designations/dropdown",
    response_model=list[DesignationDropdownResponse],
    status_code=status.HTTP_200_OK,
    summary="List active designations for dropdown",
)
async def list_designations_dropdown(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    department_id: Optional[str] = Query(None),
):
    designations = await service.list_designations_for_dropdown(
        department_id=department_id,
    )

    return [
        DesignationDropdownResponse(**designation)
        for designation in designations
    ]


@router.get(
    "/designations/statistics",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Get designation statistics",
)
async def get_designation_statistics(
    _current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    return await service.get_designation_statistics()


@router.post(
    "/designations/bulk-import",
    response_model=BulkDesignationImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk import designations",
)
async def bulk_import_designations(
    request: BulkDesignationImportRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    created_by = get_actor_id(current_user)

    designations_data = [
        designation.model_dump(exclude_none=True)
        for designation in request.designations
    ]

    result = await service.bulk_import_designations(
        designations=designations_data,
        created_by=created_by,
        skip_duplicates=request.skip_duplicates,
    )

    return BulkDesignationImportResponse(**result)


@router.get(
    "/designations/{designation_id}",
    response_model=DesignationDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get designation by ID",
)
async def get_designation(
    designation_id: str,
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    designation = await service.get_designation_by_id(
        designation_id=designation_id,
        include_details=True,
    )

    return DesignationDetailResponse(**designation)


@router.patch(
    "/designations/{designation_id}",
    response_model=DesignationUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update designation",
)
async def update_designation(
    designation_id: str,
    request: UpdateDesignationRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    designation = await service.update_designation(
        designation_id=designation_id,
        update_data=request.model_dump(exclude_none=True),
        updated_by=updated_by,
    )

    return DesignationUpdatedResponse(
        message="Designation updated successfully",
        designation=DesignationListResponse(**designation),
    )


@router.delete(
    "/designations/{designation_id}",
    response_model=DesignationDeactivatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate designation",
)
async def deactivate_designation(
    designation_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    await service.deactivate_designation(
        designation_id=designation_id,
        updated_by=updated_by,
    )

    return DesignationDeactivatedResponse(
        message="Designation deactivated successfully",
        designation_id=designation_id,
    )


@router.patch(
    "/designations/{designation_id}/activate",
    response_model=DesignationUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Reactivate designation",
)
async def activate_designation(
    designation_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    designation = await service.activate_designation(
        designation_id=designation_id,
        updated_by=updated_by,
    )

    return DesignationUpdatedResponse(
        message="Designation activated successfully",
        designation=DesignationListResponse(**designation),
    )


# -------------------------
# Leave Type Routes
# -------------------------


@router.post(
    "/leave-types",
    response_model=LeaveTypeCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new leave type",
)
async def create_leave_type(
    request: CreateLeaveTypeRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    created_by = get_actor_id(current_user)

    leave_type = await service.create_leave_type(
        leave_type_data=request.model_dump(exclude_none=True),
        created_by=created_by,
    )

    return LeaveTypeCreatedResponse(
        message="Leave type created successfully",
        leave_type_id=leave_type.get("id") or leave_type.get("_id"),
        leave_type=LeaveTypeListResponse(**leave_type),
    )


@router.get(
    "/leave-types",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="List leave types",
)
async def list_leave_types(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    is_active: Optional[bool] = Query(None),
    is_paid: Optional[bool] = Query(None),
    requires_approval: Optional[bool] = Query(None),
    requires_documentation: Optional[bool] = Query(None),
    carry_forward_allowed: Optional[bool] = Query(None),
    encashment_allowed: Optional[bool] = Query(None),
    is_accrued: Optional[bool] = Query(None),
    available_during_probation: Optional[bool] = Query(None),
    gender_specific: Optional[str] = Query(None, pattern="^(male|female)$"),
    search: Optional[str] = Query(None, min_length=2, max_length=100),
    sort_by: str = Query(
        "display_order",
        pattern=(
            "^(display_order|name|code|default_annual_grant|max_annual_limit|"
            "min_notice_days|is_paid|requires_approval|requires_documentation|"
            "carry_forward_allowed|encashment_allowed|is_accrued|created_at|updated_at)$"
        ),
    ),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    leave_types, total_count = await service.list_leave_types(
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
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )

    return {
        "leave_types": [
            LeaveTypeListResponse(**leave_type)
            for leave_type in leave_types
        ],
        "total": total_count,
        "skip": skip,
        "limit": limit,
    }


@router.get(
    "/leave-types/dropdown",
    response_model=list[LeaveTypeDropdownResponse],
    status_code=status.HTTP_200_OK,
    summary="List active leave types for dropdown",
)
async def list_leave_types_dropdown(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    gender: Optional[str] = Query(None, pattern="^(male|female)$"),
    include_unpaid: bool = Query(True),
):
    leave_types = await service.list_leave_types_for_dropdown(
        gender=gender,
        include_unpaid=include_unpaid,
    )

    return [
        LeaveTypeDropdownResponse(**leave_type)
        for leave_type in leave_types
    ]


@router.get(
    "/leave-types/statistics",
    response_model=LeaveTypeStatisticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get leave type statistics",
)
async def get_leave_type_statistics(
    _current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    statistics = await service.get_leave_type_statistics()
    return LeaveTypeStatisticsResponse(**statistics)


@router.post(
    "/leave-types/bulk-import",
    response_model=BulkLeaveTypeImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk import leave types",
)
async def bulk_import_leave_types(
    request: BulkLeaveTypeImportRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    created_by = get_actor_id(current_user)

    leave_types_data = [
        leave_type.model_dump(exclude_none=True)
        for leave_type in request.leave_types
    ]

    result = await service.bulk_import_leave_types(
        leave_types=leave_types_data,
        created_by=created_by,
        skip_duplicates=request.skip_duplicates,
    )

    return BulkLeaveTypeImportResponse(**result)


@router.get(
    "/leave-types/{leave_type_id}/rules",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Get active leave type rules by ID",
)
async def get_leave_type_rules(
    leave_type_id: str,
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    return await service.get_leave_type_rules_by_id(
        leave_type_id=leave_type_id,
    )


@router.get(
    "/leave-types/{leave_type_id}",
    response_model=LeaveTypeDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get leave type by ID",
)
async def get_leave_type(
    leave_type_id: str,
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    leave_type = await service.get_leave_type_by_id(
        leave_type_id=leave_type_id,
        include_details=True,
    )

    return LeaveTypeDetailResponse(**leave_type)


@router.patch(
    "/leave-types/{leave_type_id}",
    response_model=LeaveTypeUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update leave type",
)
async def update_leave_type(
    leave_type_id: str,
    request: UpdateLeaveTypeRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    leave_type = await service.update_leave_type(
        leave_type_id=leave_type_id,
        update_data=request.model_dump(exclude_none=True),
        updated_by=updated_by,
    )

    return LeaveTypeUpdatedResponse(
        message="Leave type updated successfully",
        leave_type=LeaveTypeListResponse(**leave_type),
    )


@router.delete(
    "/leave-types/{leave_type_id}",
    response_model=LeaveTypeDeactivatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate leave type",
)
async def deactivate_leave_type(
    leave_type_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    await service.deactivate_leave_type(
        leave_type_id=leave_type_id,
        updated_by=updated_by,
    )

    return LeaveTypeDeactivatedResponse(
        message="Leave type deactivated successfully",
        leave_type_id=leave_type_id,
    )


@router.patch(
    "/leave-types/{leave_type_id}/activate",
    response_model=LeaveTypeUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Reactivate leave type",
)
async def activate_leave_type(
    leave_type_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    leave_type = await service.activate_leave_type(
        leave_type_id=leave_type_id,
        updated_by=updated_by,
    )

    return LeaveTypeUpdatedResponse(
        message="Leave type activated successfully",
        leave_type=LeaveTypeListResponse(**leave_type),
    )


# -------------------------
# Claim Type Routes
# -------------------------


@router.post(
    "/claim-types",
    response_model=ClaimTypeCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new claim type",
)
async def create_claim_type(
    request: CreateClaimTypeRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    created_by = get_actor_id(current_user)

    claim_type = await service.create_claim_type(
        claim_type_data=request.model_dump(exclude_none=True),
        created_by=created_by,
    )

    return ClaimTypeCreatedResponse(
        message="Claim type created successfully",
        claim_type_id=claim_type.get("id") or claim_type.get("_id"),
        claim_type=ClaimTypeListResponse(**claim_type),
    )


@router.get(
    "/claim-types",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="List claim types",
)
async def list_claim_types(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    is_active: Optional[bool] = Query(None),
    requires_bill: Optional[bool] = Query(None),
    requires_approval: Optional[bool] = Query(None),
    is_taxable: Optional[bool] = Query(None),
    currency: Optional[str] = Query(None, min_length=3, max_length=3),
    search: Optional[str] = Query(None, min_length=2, max_length=100),
    sort_by: str = Query(
        "display_order",
        pattern=(
            "^(display_order|name|code|default_annual_limit|default_monthly_limit|"
            "max_claim_amount|min_claim_amount|requires_bill|requires_approval|"
            "is_taxable|currency|created_at|updated_at)$"
        ),
    ),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    claim_types, total_count = await service.list_claim_types(
        is_active=is_active,
        requires_bill=requires_bill,
        requires_approval=requires_approval,
        is_taxable=is_taxable,
        currency=currency,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )

    return {
        "claim_types": [
            ClaimTypeListResponse(**claim_type)
            for claim_type in claim_types
        ],
        "total": total_count,
        "skip": skip,
        "limit": limit,
    }


@router.get(
    "/claim-types/dropdown",
    response_model=list[ClaimTypeDropdownResponse],
    status_code=status.HTTP_200_OK,
    summary="List active claim types for dropdown",
)
async def list_claim_types_dropdown(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    include_taxable: bool = Query(True),
):
    claim_types = await service.list_claim_types_for_dropdown(
        include_taxable=include_taxable,
    )

    return [
        ClaimTypeDropdownResponse(**claim_type)
        for claim_type in claim_types
    ]


@router.get(
    "/claim-types/statistics",
    response_model=ClaimTypeStatisticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get claim type statistics",
)
async def get_claim_type_statistics(
    _current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    statistics = await service.get_claim_type_statistics()
    return ClaimTypeStatisticsResponse(**statistics)


@router.post(
    "/claim-types/bulk-import",
    response_model=BulkClaimTypeImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk import claim types",
)
async def bulk_import_claim_types(
    request: BulkClaimTypeImportRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    created_by = get_actor_id(current_user)

    claim_types_data = [
        claim_type.model_dump(exclude_none=True)
        for claim_type in request.claim_types
    ]

    result = await service.bulk_import_claim_types(
        claim_types=claim_types_data,
        created_by=created_by,
        skip_duplicates=request.skip_duplicates,
    )

    return BulkClaimTypeImportResponse(**result)


@router.patch(
    "/claim-types/bulk-update-limits",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Bulk update claim type limits",
)
async def bulk_update_claim_type_limits(
    updates: list[dict],
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    return await service.bulk_update_claim_type_limits(
        updates=updates,
        updated_by=updated_by,
    )


@router.get(
    "/claim-types/{claim_type_id}/rules",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Get active claim type rules by ID",
)
async def get_claim_type_rules(
    claim_type_id: str,
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    return await service.get_claim_type_rules_by_id(
        claim_type_id=claim_type_id,
    )


@router.get(
    "/claim-types/{claim_type_id}",
    response_model=ClaimTypeDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get claim type by ID",
)
async def get_claim_type(
    claim_type_id: str,
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    claim_type = await service.get_claim_type_by_id(
        claim_type_id=claim_type_id,
        include_details=True,
    )

    return ClaimTypeDetailResponse(**claim_type)


@router.patch(
    "/claim-types/{claim_type_id}",
    response_model=ClaimTypeUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update claim type",
)
async def update_claim_type(
    claim_type_id: str,
    request: UpdateClaimTypeRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    claim_type = await service.update_claim_type(
        claim_type_id=claim_type_id,
        update_data=request.model_dump(exclude_none=True),
        updated_by=updated_by,
    )

    return ClaimTypeUpdatedResponse(
        message="Claim type updated successfully",
        claim_type=ClaimTypeListResponse(**claim_type),
    )


@router.delete(
    "/claim-types/{claim_type_id}",
    response_model=ClaimTypeDeactivatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate claim type",
)
async def deactivate_claim_type(
    claim_type_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    await service.deactivate_claim_type(
        claim_type_id=claim_type_id,
        updated_by=updated_by,
    )

    return ClaimTypeDeactivatedResponse(
        message="Claim type deactivated successfully",
        claim_type_id=claim_type_id,
    )


@router.patch(
    "/claim-types/{claim_type_id}/activate",
    response_model=ClaimTypeUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Reactivate claim type",
)
async def activate_claim_type(
    claim_type_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    claim_type = await service.activate_claim_type(
        claim_type_id=claim_type_id,
        updated_by=updated_by,
    )

    return ClaimTypeUpdatedResponse(
        message="Claim type activated successfully",
        claim_type=ClaimTypeListResponse(**claim_type),
    )


# -------------------------
# Holiday Routes
# -------------------------


@router.post(
    "/holidays",
    response_model=HolidayCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new holiday",
)
async def create_holiday(
    request: CreateHolidayRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    created_by = get_actor_id(current_user)

    holiday = await service.create_holiday(
        holiday_data=request.model_dump(exclude_none=True),
        created_by=created_by,
    )

    return HolidayCreatedResponse(
        message="Holiday created successfully",
        holiday_id=holiday.get("id") or holiday.get("_id"),
        holiday=HolidayListResponse(**holiday),
    )


@router.get(
    "/holidays",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="List holidays",
)
async def list_holidays(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    year: Optional[int] = Query(None, ge=2020, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    type: Optional[str] = Query(
        None,
        pattern="^(national|festival|company|optional|regional)$",
    ),
    location: Optional[str] = Query(None),
    is_optional: Optional[bool] = Query(None),
    is_working_day: Optional[bool] = Query(None),
    is_half_day: Optional[bool] = Query(None),
    is_active: Optional[bool] = Query(None),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    search: Optional[str] = Query(None, min_length=2, max_length=100),
    sort_by: str = Query(
        "date",
        pattern="^(date|name|type|year|location|display_order|created_at|updated_at)$",
    ),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    holidays, total_count = await service.list_holidays(
        year=year,
        month=month,
        holiday_type=type,
        location=location,
        is_optional=is_optional,
        is_working_day=is_working_day,
        is_half_day=is_half_day,
        is_active=is_active,
        from_date=from_date,
        to_date=to_date,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
    )

    return {
        "holidays": [
            HolidayListResponse(**holiday)
            for holiday in holidays
        ],
        "total": total_count,
        "skip": skip,
        "limit": limit,
    }


@router.get(
    "/holidays/calendar",
    response_model=list[HolidayCalendarResponse],
    status_code=status.HTTP_200_OK,
    summary="List holidays for calendar",
)
async def list_holidays_calendar(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    year: int = Query(..., ge=2020, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    location: Optional[str] = Query(None),
    include_optional: bool = Query(True),
):
    holidays = await service.list_holidays_for_calendar(
        year=year,
        month=month,
        location=location,
        include_optional=include_optional,
    )

    return [
        HolidayCalendarResponse(**holiday)
        for holiday in holidays
    ]


@router.get(
    "/holidays/dropdown",
    response_model=list[HolidayDropdownResponse],
    status_code=status.HTTP_200_OK,
    summary="List holidays for dropdown",
)
async def list_holidays_dropdown(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    year: Optional[int] = Query(None, ge=2020, le=2100),
    location: Optional[str] = Query(None),
    include_optional: bool = Query(True),
):
    holidays, _total_count = await service.list_holidays(
        year=year,
        location=location,
        is_optional=None if include_optional else False,
        is_active=True,
        sort_by="date",
        sort_order="asc",
        skip=0,
        limit=500,
    )

    return [
        HolidayDropdownResponse(**holiday)
        for holiday in holidays
    ]


@router.get(
    "/holidays/upcoming",
    response_model=list[HolidayCalendarResponse],
    status_code=status.HTTP_200_OK,
    summary="List upcoming holidays",
)
async def list_upcoming_holidays(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    days: int = Query(30, ge=1, le=365),
    location: Optional[str] = Query(None),
    include_optional: bool = Query(True),
):
    holidays = await service.list_upcoming_holidays(
        days=days,
        location=location,
        include_optional=include_optional,
    )

    return [
        HolidayCalendarResponse(**holiday)
        for holiday in holidays
    ]


@router.get(
    "/holidays/statistics",
    response_model=HolidayStatisticsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get holiday statistics",
)
async def get_holiday_statistics(
    _current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    year: Optional[int] = Query(None, ge=2020, le=2100),
):
    statistics = await service.get_holiday_statistics(year=year)
    return HolidayStatisticsResponse(**statistics)


@router.post(
    "/holidays/bulk-import",
    response_model=BulkHolidayImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk import holidays",
)
async def bulk_import_holidays(
    request: BulkHolidayImportRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    created_by = get_actor_id(current_user)

    holidays_data = [
        holiday.model_dump(exclude_none=True)
        for holiday in request.holidays
    ]

    result = await service.bulk_import_holidays(
        holidays=holidays_data,
        created_by=created_by,
        skip_duplicates=request.skip_duplicates,
    )

    return BulkHolidayImportResponse(**result)


@router.get(
    "/holidays/{holiday_id}",
    response_model=HolidayDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get holiday by ID",
)
async def get_holiday(
    holiday_id: str,
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    holiday = await service.get_holiday_by_id(holiday_id=holiday_id)

    return HolidayDetailResponse(**holiday)


@router.patch(
    "/holidays/{holiday_id}",
    response_model=HolidayUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update holiday",
)
async def update_holiday(
    holiday_id: str,
    request: UpdateHolidayRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    holiday = await service.update_holiday(
        holiday_id=holiday_id,
        update_data=request.model_dump(exclude_none=True),
        updated_by=updated_by,
    )

    return HolidayUpdatedResponse(
        message="Holiday updated successfully",
        holiday=HolidayListResponse(**holiday),
    )


@router.delete(
    "/holidays/{holiday_id}",
    response_model=HolidayDeactivatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate holiday",
)
async def deactivate_holiday(
    holiday_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    await service.deactivate_holiday(
        holiday_id=holiday_id,
        updated_by=updated_by,
    )

    return HolidayDeactivatedResponse(
        message="Holiday deactivated successfully",
        holiday_id=holiday_id,
    )


@router.patch(
    "/holidays/{holiday_id}/activate",
    response_model=HolidayUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Reactivate holiday",
)
async def activate_holiday(
    holiday_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    updated_by = get_actor_id(current_user)

    holiday = await service.activate_holiday(
        holiday_id=holiday_id,
        updated_by=updated_by,
    )

    return HolidayUpdatedResponse(
        message="Holiday activated successfully",
        holiday=HolidayListResponse(**holiday),
    )