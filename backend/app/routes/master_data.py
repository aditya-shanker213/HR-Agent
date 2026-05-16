"""
Master Data routes.

All master data endpoints for:
- Departments
- Designations
- Leave Types (future)
- Claim Types (future)

Pattern:
Route -> Master Data Service -> Repository -> MongoDB

Access Control:
- Authenticated users can read master data for dropdowns
- HR/Admin can create, update, deactivate, activate
- Admin only can bulk import
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.app.database.mongo_connection import get_database
from backend.app.dependencies.auth_dependencies import (
    get_current_active_user,
    require_admin,
    require_hr,
)
from backend.app.repositories.department_repository import DepartmentRepository
from backend.app.repositories.designation_repository import DesignationRepository
from backend.app.repositories.user_repository import UserRepository
from backend.app.schemas.master_data_schema import (
    BulkDepartmentImportRequest,
    BulkDepartmentImportResponse,
    BulkDesignationImportRequest,
    BulkDesignationImportResponse,
    CreateDepartmentRequest,
    CreateDesignationRequest,
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
    UpdateDepartmentRequest,
    UpdateDesignationRequest,
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

    Dependencies:
    - DepartmentRepository uses MongoDB
    - DesignationRepository uses MongoDB
    - UserRepository is currently used for department head validation
      Later, this should be replaced with EmployeeRepository.
    """

    department_repo = DepartmentRepository(db)
    designation_repo = DesignationRepository(db)
    user_repo = UserRepository(db)

    return MasterDataService(
        department_repo=department_repo,
        designation_repo=designation_repo,
        user_repo=user_repo,
    )


def get_actor_id(current_user: dict) -> str:
    """
    Extract logged-in user's ID from current_user.

    UserRepository currently returns MongoDB _id as string.
    Some future repositories may also expose id.
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
    description=(
        "Create a new department. "
        "Department code must be unique. "
        "Requires HR or Admin role."
    ),
)
async def create_department(
    request: CreateDepartmentRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Create a new department.
    """

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
    description=(
        "List departments with filtering, search, sorting, and pagination. "
        "All authenticated users can access this endpoint."
    ),
)
async def list_departments(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    is_active: Optional[bool] = Query(
        None,
        description="Filter by active status. Omit to get all departments.",
    ),
    location: Optional[str] = Query(
        None,
        description="Filter by location or branch.",
    ),
    parent_id: Optional[str] = Query(
        None,
        description="Filter by parent department ID.",
    ),
    search: Optional[str] = Query(
        None,
        min_length=2,
        max_length=100,
        description="Search in department name, code, description, or location.",
    ),
    sort_by: str = Query(
        "display_order",
        description="Sort field.",
        pattern="^(display_order|name|code|created_at|updated_at)$",
    ),
    sort_order: str = Query(
        "asc",
        description="Sort order.",
        pattern="^(asc|desc)$",
    ),
    skip: int = Query(
        0,
        ge=0,
        description="Number of records to skip for pagination.",
    ),
    limit: int = Query(
        50,
        ge=1,
        le=100,
        description="Maximum number of records to return.",
    ),
):
    """
    List departments with filtering, search, sorting, and pagination.
    """

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
    description=(
        "Get department statistics for HR/Admin dashboard. "
        "Requires HR or Admin role."
    ),
)
async def get_department_statistics(
    _current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Get department statistics.

    Important:
    This route must stay before /departments/{department_id}
    so FastAPI does not treat 'statistics' as department_id.
    """

    return await service.get_department_statistics()


@router.post(
    "/departments/bulk-import",
    response_model=BulkDepartmentImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk import departments",
    description=(
        "Bulk import multiple departments. "
        "Useful during initial company setup or migration. "
        "Requires Admin role only."
    ),
)
async def bulk_import_departments(
    request: BulkDepartmentImportRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Bulk import departments.
    """

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
    description=(
        "Get department details by ID. "
        "Includes enriched data such as head name, parent name, "
        "employee count, and children count. "
        "All authenticated users can access this endpoint."
    ),
)
async def get_department(
    department_id: str,
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Get department by ID with enriched details.
    """

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
    description=(
        "Update department fields. "
        "All fields are optional. Only provided fields are updated. "
        "Requires HR or Admin role."
    ),
)
async def update_department(
    department_id: str,
    request: UpdateDepartmentRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Update department fields.
    """

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
    description=(
        "Deactivate department using soft delete. "
        "The document remains in MongoDB but is_active=False. "
        "Cannot deactivate if department has active child departments. "
        "Requires HR or Admin role."
    ),
)
async def deactivate_department(
    department_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Deactivate department.
    """

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
    description=(
        "Reactivate an inactive department. "
        "If the department has a parent, parent must be active. "
        "Requires HR or Admin role."
    ),
)
async def activate_department(
    department_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Reactivate an inactive department.
    """

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
    description=(
        "Create a new designation. "
        "Designation code must be unique. "
        "Requires HR or Admin role."
    ),
)
async def create_designation(
    request: CreateDesignationRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Create a new designation.

    Business rules:
    - Designation code must be unique.
    - department_id is optional.
    - If department_id is provided, department must exist and be active.
    """

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
    description=(
        "List designations with filtering, search, sorting, and pagination. "
        "All authenticated users can access this endpoint."
    ),
)
async def list_designations(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    is_active: Optional[bool] = Query(
        None,
        description="Filter by active status. Omit to get all designations.",
    ),
    department_id: Optional[str] = Query(
        None,
        description="Filter by department ID.",
    ),
    level: Optional[int] = Query(
        None,
        ge=1,
        le=10,
        description="Filter by career level.",
    ),
    search: Optional[str] = Query(
        None,
        min_length=2,
        max_length=100,
        description="Search in designation name, code, or description.",
    ),
    sort_by: str = Query(
        "display_order",
        description="Sort field.",
        pattern="^(display_order|name|code|level|department_id|created_at|updated_at)$",
    ),
    sort_order: str = Query(
        "asc",
        description="Sort order.",
        pattern="^(asc|desc)$",
    ),
    skip: int = Query(
        0,
        ge=0,
        description="Number of records to skip for pagination.",
    ),
    limit: int = Query(
        50,
        ge=1,
        le=100,
        description="Maximum number of records to return.",
    ),
):
    """
    List designations with filtering, search, sorting, and pagination.
    """

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
    description=(
        "Return lightweight active designation list for frontend dropdowns. "
        "All authenticated users can access this endpoint."
    ),
)
async def list_designations_dropdown(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
    department_id: Optional[str] = Query(
        None,
        description="Optional department ID. If provided, returns department-specific and global designations.",
    ),
    include_global: bool = Query(
        True,
        description="Include global designations where department_id is not set.",
    ),
):
    """
    List active designations for frontend dropdowns.

    Important:
    This route must stay before /designations/{designation_id}.
    """

    designations = await service.list_designations_for_dropdown(
        department_id=department_id,
        include_global=include_global,
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
    description=(
        "Get designation statistics for HR/Admin dashboard. "
        "Requires HR or Admin role."
    ),
)
async def get_designation_statistics(
    _current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Get designation statistics.

    Important:
    This route must stay before /designations/{designation_id}.
    """

    return await service.get_designation_statistics()


@router.post(
    "/designations/bulk-import",
    response_model=BulkDesignationImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk import designations",
    description=(
        "Bulk import multiple designations. "
        "Useful during initial company setup or migration. "
        "Requires Admin role only."
    ),
)
async def bulk_import_designations(
    request: BulkDesignationImportRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Bulk import designations.

    Important:
    This route must stay before /designations/{designation_id}.
    """

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
    description=(
        "Get designation details by ID. "
        "Includes enriched data such as department name, department code, "
        "and employee count. "
        "All authenticated users can access this endpoint."
    ),
)
async def get_designation(
    designation_id: str,
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Get designation by ID with enriched details.
    """

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
    description=(
        "Update designation fields. "
        "All fields are optional. Only provided fields are updated. "
        "Requires HR or Admin role."
    ),
)
async def update_designation(
    designation_id: str,
    request: UpdateDesignationRequest,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Update designation fields.
    """

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
    description=(
        "Deactivate designation using soft delete. "
        "The document remains in MongoDB but is_active=False. "
        "Requires HR or Admin role."
    ),
)
async def deactivate_designation(
    designation_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Deactivate designation.
    """

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
    description=(
        "Reactivate an inactive designation. "
        "If the designation is linked to a department, department must be active. "
        "Requires HR or Admin role."
    ),
)
async def activate_designation(
    designation_id: str,
    current_user: Annotated[dict, Depends(require_hr)],
    service: Annotated[MasterDataService, Depends(get_master_data_service)],
):
    """
    Reactivate an inactive designation.
    """

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
# Future: Leave Type Routes
# -------------------------

# TODO: Add leave type endpoints after creating leave_type_model.py
# POST   /api/v1/master-data/leave-types
# GET    /api/v1/master-data/leave-types
# GET    /api/v1/master-data/leave-types/{id}
# PATCH  /api/v1/master-data/leave-types/{id}
# DELETE /api/v1/master-data/leave-types/{id}


# -------------------------
# Future: Claim Type Routes
# -------------------------

# TODO: Add claim type endpoints after creating claim_type_model.py
# POST   /api/v1/master-data/claim-types
# GET    /api/v1/master-data/claim-types
# GET    /api/v1/master-data/claim-types/{id}
# PATCH  /api/v1/master-data/claim-types/{id}
# DELETE /api/v1/master-data/claim-types/{id}