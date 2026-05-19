"""
Company Settings API routes.

Endpoints are mounted by main.py with settings.API_PREFIX.

Final paths:
- POST   /api/v1/settings
- POST   /api/v1/settings/initialize
- GET    /api/v1/settings
- GET    /api/v1/settings/status
- GET    /api/v1/settings/summary
- PUT    /api/v1/settings
- PATCH  /api/v1/settings
- POST   /api/v1/settings/deactivate
- POST   /api/v1/settings/activate

Section endpoints:
- GET    /api/v1/settings/sections/{section_name}
- PUT    /api/v1/settings/sections/{section_name}
- PATCH  /api/v1/settings/sections/{section_name}

Convenience section endpoints:
- GET    /api/v1/settings/company-info
- PUT    /api/v1/settings/company-info
- PATCH  /api/v1/settings/company-info

- GET    /api/v1/settings/system
- PUT    /api/v1/settings/system
- PATCH  /api/v1/settings/system

- GET    /api/v1/settings/work-week
- PUT    /api/v1/settings/work-week
- PATCH  /api/v1/settings/work-week

- GET    /api/v1/settings/leave-policy
- PUT    /api/v1/settings/leave-policy
- PATCH  /api/v1/settings/leave-policy

- GET    /api/v1/settings/payroll
- PUT    /api/v1/settings/payroll
- PATCH  /api/v1/settings/payroll

- GET    /api/v1/settings/claim-policy
- PUT    /api/v1/settings/claim-policy
- PATCH  /api/v1/settings/claim-policy

Pattern:
Route → Service → Repository → MongoDB

Access:
- Authenticated users can read settings and sections
- Admin users can create/update/patch/activate/deactivate settings
"""

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Path, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.app.database.mongo_connection import get_database
from backend.app.dependencies.auth_dependencies import (
    get_current_active_user,
    require_admin,
)
from backend.app.schemas.company_setting_schema import (
    CompanySettingsCreatedResponse,
    CompanySettingsExistsResponse,
    CompanySettingsInitializedResponse,
    CompanySettingsResponse,
    CompanySettingsSectionResponse,
    CompanySettingsStatusResponse,
    CompanySettingsSummaryResponse,
    CompanySettingsUpdatedResponse,
    CreateCompanySettingsRequest,
    InitializeCompanySettingsRequest,
    PatchClaimPolicyRequest,
    PatchCompanyInfoRequest,
    PatchCompanySettingsRequest,
    PatchLeavePolicyRequest,
    PatchPayrollRequest,
    PatchSystemConfigRequest,
    PatchWorkWeekRequest,
    UpdateClaimPolicyRequest,
    UpdateCompanyInfoRequest,
    UpdateCompanySettingsRequest,
    UpdateLeavePolicyRequest,
    UpdatePayrollRequest,
    UpdateSystemConfigRequest,
    UpdateWorkWeekRequest,
)
from backend.app.services.company_setting_service import CompanySettingsService


router = APIRouter(prefix="/settings", tags=["Company Settings"])


# -------------------------
# Dependency injection
# -------------------------


async def get_company_settings_service(
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> CompanySettingsService:
    """
    Create CompanySettingsService instance.
    """
    return CompanySettingsService(db=db)


def get_actor_id(current_user: dict) -> str:
    """
    Extract logged-in user's ID from current_user.
    """

    actor_id = current_user.get("id") or current_user.get("_id")

    if not actor_id:
        actor_id = current_user.get("username", "system")

    return str(actor_id)


CompanySettingsSectionName = Literal[
    "company_info",
    "system",
    "work_week",
    "leave_policy",
    "payroll",
    "claim_policy",
]


# -------------------------
# Create / Initialize
# -------------------------


@router.post(
    "",
    response_model=CompanySettingsCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create company settings",
    description="Create complete company settings. Requires Admin role.",
)
async def create_company_settings(
    request: CreateCompanySettingsRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
):
    """
    Create complete company settings.

    Usually used once during setup.
    """

    created_by = get_actor_id(current_user)

    return await service.create_settings(
        request=request,
        created_by=created_by,
    )


@router.post(
    "/initialize",
    response_model=CompanySettingsInitializedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initialize default company settings",
    description=(
        "Initialize company settings with minimal required company information. "
        "All other settings use defaults. Requires Admin role."
    ),
)
async def initialize_company_settings(
    request: InitializeCompanySettingsRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
):
    """
    Initialize company settings with minimum company information.
    """

    created_by = get_actor_id(current_user)

    return await service.initialize_default_settings(
        request=request,
        created_by=created_by,
    )


# -------------------------
# Read operations
# -------------------------


@router.get(
    "",
    response_model=CompanySettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get company settings",
    description="Get company settings. Available to all authenticated users.",
)
async def get_company_settings(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
    include_inactive: bool = Query(
        default=False,
        description="Allow returning inactive settings. Useful for admin recovery.",
    ),
):
    """
    Get full company settings.
    """

    return await service.get_settings(
        company_id=company_id,
        include_inactive=include_inactive,
    )


@router.get(
    "/status",
    response_model=CompanySettingsExistsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get company settings status",
    description="Check whether company settings exist and whether they are active.",
)
async def get_company_settings_status(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Get company settings existence and active status.

    Important:
    This route must stay before /{settings_id}.
    """

    return await service.get_settings_status(company_id=company_id)


@router.get(
    "/summary",
    response_model=CompanySettingsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get company settings summary",
    description="Get lightweight company settings summary.",
)
async def get_company_settings_summary(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Get lightweight company settings summary.

    Important:
    This route must stay before /{settings_id}.
    """

    return await service.get_summary(company_id=company_id)


@router.get(
    "/by-id/{settings_id}",
    response_model=CompanySettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get company settings by ID",
    description="Get company settings by MongoDB ID.",
)
async def get_company_settings_by_id(
    settings_id: str,
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
):
    """
    Get company settings by ID.
    """

    return await service.get_settings_by_id(settings_id=settings_id)


# -------------------------
# Generic section operations
# -------------------------


@router.get(
    "/sections/{section_name}",
    response_model=CompanySettingsSectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get settings section",
    description="Get one company settings section dynamically.",
)
async def get_settings_section(
    section_name: CompanySettingsSectionName = Path(...),
    _current_user: Annotated[dict, Depends(get_current_active_user)] = None,
    service: Annotated[
        CompanySettingsService,
        Depends(get_company_settings_service),
    ] = None,
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Get one settings section dynamically.

    Allowed section names:
    - company_info
    - system
    - work_week
    - leave_policy
    - payroll
    - claim_policy
    """

    return await service.get_section(
        section_name=section_name,
        company_id=company_id,
    )


@router.put(
    "/sections/{section_name}",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update settings section",
    description="Replace one company settings section. Requires Admin role.",
)
async def update_settings_section(
    section_data: dict,
    section_name: CompanySettingsSectionName = Path(...),
    current_user: Annotated[dict, Depends(require_admin)] = None,
    service: Annotated[
        CompanySettingsService,
        Depends(get_company_settings_service),
    ] = None,
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Replace one settings section dynamically.
    """

    updated_by = get_actor_id(current_user)

    return await service.update_section(
        company_id=company_id,
        section_name=section_name,
        section_data=section_data,
        updated_by=updated_by,
    )


@router.patch(
    "/sections/{section_name}",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Patch settings section",
    description="Partially update one company settings section. Requires Admin role.",
)
async def patch_settings_section(
    section_data: dict,
    section_name: CompanySettingsSectionName = Path(...),
    current_user: Annotated[dict, Depends(require_admin)] = None,
    service: Annotated[
        CompanySettingsService,
        Depends(get_company_settings_service),
    ] = None,
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Partially patch one settings section dynamically.
    """

    updated_by = get_actor_id(current_user)

    return await service.patch_section(
        company_id=company_id,
        section_name=section_name,
        section_data=section_data,
        updated_by=updated_by,
    )


# -------------------------
# Convenience section read routes
# -------------------------


@router.get(
    "/company-info",
    response_model=CompanySettingsSectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get company information",
    description="Get company_info section.",
)
async def get_company_info(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    return await service.get_company_info(company_id=company_id)


@router.get(
    "/system",
    response_model=CompanySettingsSectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get system configuration",
    description="Get system section.",
)
async def get_system_config(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    return await service.get_system_config(company_id=company_id)


@router.get(
    "/work-week",
    response_model=CompanySettingsSectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get work week configuration",
    description="Get work_week section.",
)
async def get_work_week(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    return await service.get_work_week(company_id=company_id)


@router.get(
    "/leave-policy",
    response_model=CompanySettingsSectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get leave policy configuration",
    description="Get leave_policy section.",
)
async def get_leave_policy(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    return await service.get_leave_policy(company_id=company_id)


@router.get(
    "/payroll",
    response_model=CompanySettingsSectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get payroll configuration",
    description="Get payroll section.",
)
async def get_payroll_config(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    return await service.get_payroll(company_id=company_id)


@router.get(
    "/claim-policy",
    response_model=CompanySettingsSectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get claim policy configuration",
    description="Get claim_policy section.",
)
async def get_claim_policy(
    _current_user: Annotated[dict, Depends(get_current_active_user)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    return await service.get_claim_policy(company_id=company_id)


# -------------------------
# Update full settings / patch settings
# -------------------------


@router.put(
    "",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update company settings",
    description="Replace selected full sections in company settings. Requires Admin role.",
)
async def update_company_settings(
    request: UpdateCompanySettingsRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Replace selected full settings sections.
    """

    updated_by = get_actor_id(current_user)

    return await service.update_settings(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


@router.patch(
    "",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Patch company settings",
    description="Partially update nested company settings. Requires Admin role.",
)
async def patch_company_settings(
    request: PatchCompanySettingsRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Patch nested company settings.
    """

    updated_by = get_actor_id(current_user)

    return await service.patch_settings(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


# -------------------------
# Convenience section update routes
# -------------------------


@router.put(
    "/company-info",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update company information",
    description="Replace company_info section. Requires Admin role.",
)
async def update_company_info(
    request: UpdateCompanyInfoRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    updated_by = get_actor_id(current_user)

    return await service.update_company_info(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


@router.patch(
    "/company-info",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Patch company information",
    description="Patch company_info section. Requires Admin role.",
)
async def patch_company_info(
    request: PatchCompanyInfoRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    updated_by = get_actor_id(current_user)

    return await service.patch_company_info(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


@router.put(
    "/system",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update system configuration",
    description="Replace system section. Requires Admin role.",
)
async def update_system_config(
    request: UpdateSystemConfigRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    updated_by = get_actor_id(current_user)

    return await service.update_system_config(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


@router.patch(
    "/system",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Patch system configuration",
    description="Patch system section. Requires Admin role.",
)
async def patch_system_config(
    request: PatchSystemConfigRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    updated_by = get_actor_id(current_user)

    return await service.patch_system_config(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


@router.put(
    "/work-week",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update work week configuration",
    description="Replace work_week section. Requires Admin role.",
)
async def update_work_week_config(
    request: UpdateWorkWeekRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    updated_by = get_actor_id(current_user)

    return await service.update_work_week(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


@router.patch(
    "/work-week",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Patch work week configuration",
    description="Patch work_week section. Requires Admin role.",
)
async def patch_work_week_config(
    request: PatchWorkWeekRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    updated_by = get_actor_id(current_user)

    return await service.patch_work_week(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


@router.put(
    "/leave-policy",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update leave policy configuration",
    description="Replace leave_policy section. Requires Admin role.",
)
async def update_leave_policy_config(
    request: UpdateLeavePolicyRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    updated_by = get_actor_id(current_user)

    return await service.update_leave_policy(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


@router.patch(
    "/leave-policy",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Patch leave policy configuration",
    description="Patch leave_policy section. Requires Admin role.",
)
async def patch_leave_policy_config(
    request: PatchLeavePolicyRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    updated_by = get_actor_id(current_user)

    return await service.patch_leave_policy(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


@router.put(
    "/payroll",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update payroll configuration",
    description="Replace payroll section. Requires Admin role.",
)
async def update_payroll_config(
    request: UpdatePayrollRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    updated_by = get_actor_id(current_user)

    return await service.update_payroll(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


@router.patch(
    "/payroll",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Patch payroll configuration",
    description="Patch payroll section. Requires Admin role.",
)
async def patch_payroll_config(
    request: PatchPayrollRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    updated_by = get_actor_id(current_user)

    return await service.patch_payroll(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


@router.put(
    "/claim-policy",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Update claim policy configuration",
    description="Replace claim_policy section. Requires Admin role.",
)
async def update_claim_policy_config(
    request: UpdateClaimPolicyRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    updated_by = get_actor_id(current_user)

    return await service.update_claim_policy(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


@router.patch(
    "/claim-policy",
    response_model=CompanySettingsUpdatedResponse,
    status_code=status.HTTP_200_OK,
    summary="Patch claim policy configuration",
    description="Patch claim_policy section. Requires Admin role.",
)
async def patch_claim_policy_config(
    request: PatchClaimPolicyRequest,
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    updated_by = get_actor_id(current_user)

    return await service.patch_claim_policy(
        company_id=company_id,
        request=request,
        updated_by=updated_by,
    )


# -------------------------
# Activate / Deactivate
# -------------------------


@router.post(
    "/deactivate",
    response_model=CompanySettingsStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate company settings",
    description=(
        "Deactivate company settings. Requires Admin role. "
        "Warning: this can affect HR operations."
    ),
)
async def deactivate_company_settings(
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Deactivate company settings.
    """

    updated_by = get_actor_id(current_user)

    return await service.deactivate_settings(
        company_id=company_id,
        updated_by=updated_by,
    )


@router.post(
    "/activate",
    response_model=CompanySettingsStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate company settings",
    description="Reactivate company settings. Requires Admin role.",
)
async def activate_company_settings(
    current_user: Annotated[dict, Depends(require_admin)],
    service: Annotated[CompanySettingsService, Depends(get_company_settings_service)],
    company_id: str = Query(default="default", description="Company identifier"),
):
    """
    Reactivate company settings.
    """

    updated_by = get_actor_id(current_user)

    return await service.activate_settings(
        company_id=company_id,
        updated_by=updated_by,
    )