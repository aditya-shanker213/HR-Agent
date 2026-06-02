"""
Claim routes - API endpoints for claim/reimbursement management.

Pattern:
Route → Service → Repository → MongoDB

This file handles:
- HTTP request/response
- Authentication and authorization
- Input validation
- Error handling
- Response formatting

Important:
- Routes should be thin and delegate business logic to service layer.
- Use auth dependencies for access control.
- Return proper HTTP status codes.
- Never write MongoDB queries directly in routes.
- AI must never approve claims.
- Claim auto approval is disabled.
- Submitted claims go through manager/HR approval and finance approval if required.

Production/MVP note:
- In MVP/local mode, MongoDB acts as mock HRMS.
- In production HRMS read-only mode, write routes should be disabled by service
  or routed to approved HRMS/company workflow APIs.
"""

from __future__ import annotations

from datetime import date as Date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.app.database.mongo_connection import get_database
from backend.app.dependencies.auth_dependencies import (
    get_current_active_user,
    require_admin,
    require_hr,
    require_manager,
)
from backend.app.models.claim_model import (
    ClaimApproverRole,
    ClaimPaymentStatus,
    ClaimPriority,
    ClaimSource,
    ClaimStatus,
)
from backend.app.repositories.claim_repository import ClaimRepository
from backend.app.repositories.claim_type_repository import ClaimTypeRepository
from backend.app.repositories.employee_repository import EmployeeRepository
from backend.app.schemas.claim_schema import (
    AddClaimAttachmentRequest,
    ApproveClaimRequest,
    CancelClaimRequest,
    ClaimDashboardFilters,
    ClaimListFilters,
    CreateClaimDraftRequest,
    CreateClaimRequest,
    ImportClaimFromHRMSRequest,
    MarkClaimPaidRequest,
    MarkClaimPaymentFailedRequest,
    PendingApprovalsFilters,
    RejectClaimRequest,
    ResubmitClaimRequest,
    SendBackClaimRequest,
    StartClaimPaymentProcessingRequest,
    SubmitClaimRequest,
    UpdateClaimRequest,
    UpdatePaymentStatusRequest,
    ValidateClaimRequest,
    VerifyClaimAttachmentRequest,
    WithdrawClaimRequest,
)
from backend.app.services.claim_service import ClaimService


router = APIRouter(prefix="/claims", tags=["Claims Management"])


# -------------------------
# Dependency helpers
# -------------------------


def get_claim_service(db: AsyncIOMotorDatabase = Depends(get_database)) -> ClaimService:
    """
    Get claim service instance.

    For now mode is local MVP:
    - MongoDB acts as mock HRMS.
    - HRMS imported records are read-only.
    - Claim auto approval is disabled.
    """
    claim_repo = ClaimRepository(db)
    claim_type_repo = ClaimTypeRepository(db)
    employee_repo = EmployeeRepository(db)

    company_settings_repo = None

    try:
        from backend.app.repositories.company_settings_repository import (
            CompanySettingsRepository,
        )

        company_settings_repo = CompanySettingsRepository(db)
    except Exception:
        try:
            from backend.app.repositories.company_settings_repository import (
                CompanySettingsRepository,
            )

            company_settings_repo = CompanySettingsRepository(db)
        except Exception:
            company_settings_repo = None

    return ClaimService(
        claim_repo=claim_repo,
        claim_type_repo=claim_type_repo,
        employee_repo=employee_repo,
        company_settings_repo=company_settings_repo,
    )


def get_current_employee_id(current_user: dict) -> str:
    """
    Extract linked employee_id from current user.

    Auth token/user document must include employee_id.
    """
    employee_id = current_user.get("employee_id")

    if not employee_id:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="User is not linked to an employee profile",
        )

    return str(employee_id)


def get_current_user_id(current_user: dict) -> str:
    """
    Extract best available user/employee ID.
    """
    return str(
        current_user.get("employee_id")
        or current_user.get("id")
        or current_user.get("_id")
        or "system"
    )


def get_current_user_role(current_user: dict) -> str:
    """
    Normalize user role from current user.
    """
    role = current_user.get("role", "")

    if hasattr(role, "value"):
        role = role.value

    return str(role).strip().lower()


def get_current_user_display_name(current_user: dict) -> Optional[str]:
    """
    Best-effort display name from current user.
    """
    return (
        current_user.get("full_name")
        or current_user.get("name")
        or current_user.get("username")
        or current_user.get("email")
    )


def get_claim_approver_role(current_user: dict) -> Optional[ClaimApproverRole]:
    """
    Map authenticated user role to claim approver role.
    """
    role = get_current_user_role(current_user)

    if role == "manager":
        return ClaimApproverRole.MANAGER

    if role == "finance":
        return ClaimApproverRole.FINANCE

    if role == "hr":
        return ClaimApproverRole.HR

    if role == "admin":
        return ClaimApproverRole.ADMIN

    return None


def is_manager_user(current_user: dict) -> bool:
    """
    Check if user has manager-level claim access.
    """
    return get_current_user_role(current_user) in {"manager", "hr", "admin"}


def is_hr_user(current_user: dict) -> bool:
    """
    Check if user has HR-level claim access.
    """
    return get_current_user_role(current_user) in {"hr", "admin"}


def is_admin_user(current_user: dict) -> bool:
    """
    Check if user is admin.
    """
    return get_current_user_role(current_user) == "admin"


def is_finance_user(current_user: dict) -> bool:
    """
    Check if user has finance-level claim access.

    If your project does not have FINANCE role yet, HR/Admin will handle payment.
    """
    return get_current_user_role(current_user) in {"finance", "hr", "admin"}


def raise_service_error(result: dict) -> None:
    """
    Convert service error response to HTTPException.
    """
    error_code = result.get("error_code")
    message = result.get("message", "Request failed")

    status_code = http_status.HTTP_400_BAD_REQUEST

    if error_code in {"CLAIM_NOT_FOUND", "EMPLOYEE_NOT_FOUND", "CLAIM_TYPE_NOT_FOUND"}:
        status_code = http_status.HTTP_404_NOT_FOUND

    elif error_code in {"ACCESS_DENIED", "CLAIM_READ_ONLY"}:
        status_code = http_status.HTTP_403_FORBIDDEN

    elif error_code in {
        "CLAIM_NOT_EDITABLE",
        "CLAIM_NOT_APPROVABLE",
        "CLAIM_NOT_REJECTABLE",
        "CLAIM_NOT_CANCELLABLE",
        "CLAIM_NOT_WITHDRAWABLE",
        "CLAIM_NOT_SUBMITTABLE",
        "CLAIM_NOT_PAYABLE",
        "CLAIM_NOT_APPROVED",
        "CLAIM_NOT_SENT_BACK",
    }:
        status_code = http_status.HTTP_409_CONFLICT

    raise HTTPException(
        status_code=status_code,
        detail={
            "message": message,
            "error_code": error_code,
            "details": result.get("details"),
        },
    )


def unwrap_service_result(result: dict) -> dict:
    """
    Return service result as-is.

    Service already returns:
    {
        "success": bool,
        "message": str,
        "data": {...}
    }
    """
    return result


# -------------------------
# Capability endpoint
# Keep static endpoints before /{claim_id}
# -------------------------


@router.get(
    "/capabilities",
    response_model=dict,
    summary="Get claim module capabilities",
    description="Shows what claim actions are enabled in current deployment mode.",
)
async def get_claim_capabilities():
    """
    Get claim module capabilities.

    Claim auto approval is intentionally disabled.
    """
    return {
        "success": True,
        "message": "Claim module capabilities",
        "data": {
            "version": "2.0.0",
            "features": [
                "claim_submission",
                "draft_claims",
                "duplicate_detection",
                "monthly_yearly_limits",
                "bill_attachments",
                "human_approval_workflow",
                "manager_approval",
                "hr_approval_fallback",
                "finance_approval",
                "payment_processing",
                "statistics",
                "dashboard",
                "hrms_read_only_import",
            ],
            "disabled_features": [
                "claim_auto_approval",
                "ai_claim_approval",
            ],
            "approval_rule": (
                "Claims are never auto-approved by AI/service. "
                "Submitted claims require human approval."
            ),
            "supported_statuses": [item.value for item in ClaimStatus],
            "supported_priorities": [item.value for item in ClaimPriority],
            "supported_sources": [item.value for item in ClaimSource],
            "supported_payment_statuses": [item.value for item in ClaimPaymentStatus],
            "duplicate_detection_window_hours": 48,
            "max_attachment_size_mb": 10,
        },
    }


# -------------------------
# Create claim endpoints
# -------------------------


@router.post(
    "",
    response_model=dict,
    status_code=http_status.HTTP_201_CREATED,
    summary="Create claim",
    description="Employee creates a new claim. Claim goes to human approval workflow.",
)
async def create_claim(
    request: CreateClaimRequest,
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Create a new claim for logged-in employee.

    Auto approval is disabled.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.create_claim(
            employee_id=employee_id,
            request=request,
            created_by=employee_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create claim: {str(exc)}",
        )


@router.post(
    "/draft",
    response_model=dict,
    status_code=http_status.HTTP_201_CREATED,
    summary="Create draft claim",
    description="Save a partial claim as draft for later completion.",
)
async def create_draft_claim(
    request: CreateClaimDraftRequest,
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Create a draft claim.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.create_draft_claim(
            employee_id=employee_id,
            request=request,
            created_by=employee_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create draft claim: {str(exc)}",
        )


@router.post(
    "/hrms/import",
    response_model=dict,
    status_code=http_status.HTTP_201_CREATED,
    summary="Import HRMS claim record",
    description="Import a read-only HRMS claim record. Admin only.",
    dependencies=[Depends(require_admin)],
)
async def import_claim_from_hrms(
    request: ImportClaimFromHRMSRequest,
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Import read-only claim from external HRMS.

    Admin/system-only operation.
    """
    try:
        imported_by = get_current_user_id(current_user)

        success, result = await service.import_claim_from_hrms(
            request=request,
            imported_by=imported_by,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import HRMS claim: {str(exc)}",
        )


# -------------------------
# My claim endpoints
# -------------------------


@router.get(
    "/me",
    response_model=dict,
    summary="Get my claims",
    description="Get claims for logged-in employee.",
)
async def get_my_claims(
    company_id: str = Query(default="default"),
    claim_status: Optional[ClaimStatus] = Query(default=None, alias="status"),
    source: Optional[ClaimSource] = Query(default=None),
    claim_type_id: Optional[str] = Query(default=None),
    claim_type_code: Optional[str] = Query(default=None),
    priority: Optional[ClaimPriority] = Query(default=None),
    payment_status: Optional[ClaimPaymentStatus] = Query(default=None),
    is_read_only: Optional[bool] = Query(default=None),
    from_date: Optional[Date] = Query(default=None),
    to_date: Optional[Date] = Query(default=None),
    min_amount: Optional[float] = Query(default=None, ge=0),
    max_amount: Optional[float] = Query(default=None, ge=0),
    search: Optional[str] = Query(default=None, min_length=2, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Get claim requests for logged-in employee.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        filters = ClaimListFilters(
            company_id=company_id,
            status=claim_status,
            source=source,
            claim_type_id=claim_type_id,
            claim_type_code=claim_type_code,
            priority=priority,
            payment_status=payment_status,
            is_read_only=is_read_only,
            from_date=from_date,
            to_date=to_date,
            min_amount=min_amount,
            max_amount=max_amount,
            search=search,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        success, result = await service.list_my_claims(
            employee_id=employee_id,
            filters=filters,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get claims: {str(exc)}",
        )


@router.get(
    "/me/statistics",
    response_model=dict,
    summary="Get my claim statistics",
    description="Get claim statistics for logged-in employee.",
)
async def get_my_claim_statistics(
    company_id: str = Query(default="default"),
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Get claim statistics for logged-in employee.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.get_my_statistics(
            employee_id=employee_id,
            company_id=company_id,
            year=year,
            month=month,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get claim statistics: {str(exc)}",
        )


# -------------------------
# Validation / limit endpoints
# -------------------------


@router.post(
    "/validate",
    response_model=dict,
    summary="Validate claim before submission",
    description="Validate claim limits, duplicate risk, bill requirement, and approval preview.",
)
async def validate_claim(
    request: ValidateClaimRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Validate claim before actual creation/submission.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.validate_claim(
            employee_id=employee_id,
            request=request,
            company_id=company_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate claim: {str(exc)}",
        )


@router.get(
    "/check-limit/{claim_type_id}",
    response_model=dict,
    summary="Check claim limit",
    description="Check if proposed claim amount is within allowed claim limits.",
)
async def check_claim_limit(
    claim_type_id: str,
    amount: float = Query(..., gt=0, description="Proposed claim amount"),
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Check claim limit before submission.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.check_claim_limit(
            employee_id=employee_id,
            claim_type_id=claim_type_id,
            amount=amount,
            company_id=company_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check claim limit: {str(exc)}",
        )


# -------------------------
# List/search/filter endpoints
# -------------------------


@router.get(
    "",
    response_model=dict,
    summary="List claims",
    description="List/filter claims. HR/Admin can view all claims.",
    dependencies=[Depends(require_hr)],
)
async def list_claims(
    company_id: str = Query(default="default"),
    claim_status: Optional[ClaimStatus] = Query(default=None, alias="status"),
    source: Optional[ClaimSource] = Query(default=None),
    claim_type_id: Optional[str] = Query(default=None),
    claim_type_code: Optional[str] = Query(default=None),
    employee_id: Optional[str] = Query(default=None),
    employee_code: Optional[str] = Query(default=None),
    department_id: Optional[str] = Query(default=None),
    manager_id: Optional[str] = Query(default=None),
    priority: Optional[ClaimPriority] = Query(default=None),
    payment_status: Optional[ClaimPaymentStatus] = Query(default=None),
    is_read_only: Optional[bool] = Query(default=None),
    from_date: Optional[Date] = Query(default=None),
    to_date: Optional[Date] = Query(default=None),
    min_amount: Optional[float] = Query(default=None, ge=0),
    max_amount: Optional[float] = Query(default=None, ge=0),
    search: Optional[str] = Query(default=None, min_length=2, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    service: ClaimService = Depends(get_claim_service),
):
    """
    List all claims for HR/Admin.
    """
    try:
        filters = ClaimListFilters(
            company_id=company_id,
            status=claim_status,
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
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        success, result = await service.list_all_claims(filters=filters)

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list claims: {str(exc)}",
        )


# -------------------------
# Approval endpoints
# -------------------------


@router.get(
    "/pending-approvals",
    response_model=dict,
    summary="Get pending claim approvals",
    description="Get claims pending approval for current manager/HR user.",
    dependencies=[Depends(require_manager)],
)
async def get_pending_claim_approvals(
    company_id: str = Query(default="default"),
    approver_role: Optional[ClaimApproverRole] = Query(default=None),
    claim_type_id: Optional[str] = Query(default=None),
    department_id: Optional[str] = Query(default=None),
    priority: Optional[ClaimPriority] = Query(default=None),
    min_amount: Optional[float] = Query(default=None, ge=0),
    max_amount: Optional[float] = Query(default=None, ge=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Get claims pending approval.

    Manager sees own pending approvals.
    HR/Admin can see broader pending approvals.
    """
    try:
        employee_id = get_current_employee_id(current_user)
        user_role = get_current_user_role(current_user)

        filters = PendingApprovalsFilters(
            company_id=company_id,
            approver_role=approver_role,
            claim_type_id=claim_type_id,
            department_id=department_id,
            priority=priority,
            min_amount=min_amount,
            max_amount=max_amount,
            page=page,
            page_size=page_size,
        )

        approver_id = employee_id if user_role == "manager" else None

        success, result = await service.get_pending_approvals(
            filters=filters,
            approver_id=approver_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get pending claim approvals: {str(exc)}",
        )


@router.post(
    "/{claim_id}/approve",
    response_model=dict,
    summary="Approve claim",
    description="Manager/HR/Finance approves current pending approval step.",
    dependencies=[Depends(require_manager)],
)
async def approve_claim(
    claim_id: str,
    request: ApproveClaimRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Approve a pending claim step.

    Only human approvers should approve.
    AI must never call approval directly.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.approve_claim(
            claim_id=claim_id,
            approver_id=employee_id,
            request=request,
            company_id=company_id,
            approver_name=get_current_user_display_name(current_user),
            approver_role=get_claim_approver_role(current_user),
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to approve claim: {str(exc)}",
        )


@router.post(
    "/{claim_id}/reject",
    response_model=dict,
    summary="Reject claim",
    description="Manager/HR/Finance rejects current pending approval step.",
    dependencies=[Depends(require_manager)],
)
async def reject_claim(
    claim_id: str,
    request: RejectClaimRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Reject a pending claim.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.reject_claim(
            claim_id=claim_id,
            approver_id=employee_id,
            request=request,
            company_id=company_id,
            approver_name=get_current_user_display_name(current_user),
            approver_role=get_claim_approver_role(current_user),
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reject claim: {str(exc)}",
        )


@router.post(
    "/{claim_id}/send-back",
    response_model=dict,
    summary="Send claim back",
    description="Send claim back to employee for correction.",
    dependencies=[Depends(require_manager)],
)
async def send_back_claim(
    claim_id: str,
    request: SendBackClaimRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Send claim back to employee for correction.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.send_back_claim(
            claim_id=claim_id,
            actor_id=employee_id,
            request=request,
            company_id=company_id,
            actor_name=get_current_user_display_name(current_user),
            actor_role=get_claim_approver_role(current_user),
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send claim back: {str(exc)}",
        )


# -------------------------
# Update / submit / cancel / withdraw endpoints
# -------------------------


@router.patch(
    "/{claim_id}",
    response_model=dict,
    summary="Update claim",
    description="Update draft or sent-back claim.",
)
async def update_claim(
    claim_id: str,
    request: UpdateClaimRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Update claim.

    Only draft or sent-back claims can be updated.
    HRMS read-only claims cannot be edited locally.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.update_claim(
            claim_id=claim_id,
            employee_id=employee_id,
            request=request,
            company_id=company_id,
            updated_by=employee_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update claim: {str(exc)}",
        )


@router.post(
    "/{claim_id}/submit",
    response_model=dict,
    summary="Submit claim",
    description="Submit a draft or sent-back claim for human approval.",
)
async def submit_claim(
    claim_id: str,
    request: SubmitClaimRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Submit a draft/sent-back claim.

    Auto approval is disabled.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.submit_claim(
            claim_id=claim_id,
            employee_id=employee_id,
            request=request,
            company_id=company_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit claim: {str(exc)}",
        )


@router.post(
    "/{claim_id}/resubmit",
    response_model=dict,
    summary="Resubmit claim",
    description="Resubmit a sent-back claim after correction.",
)
async def resubmit_claim(
    claim_id: str,
    request: ResubmitClaimRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Resubmit a sent-back claim.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.resubmit_claim(
            claim_id=claim_id,
            employee_id=employee_id,
            request=request,
            company_id=company_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resubmit claim: {str(exc)}",
        )


@router.post(
    "/{claim_id}/cancel",
    response_model=dict,
    summary="Cancel claim",
    description="Employee cancels their own claim.",
)
async def cancel_claim(
    claim_id: str,
    request: CancelClaimRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Cancel own claim.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.cancel_claim(
            claim_id=claim_id,
            employee_id=employee_id,
            request=request,
            company_id=company_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel claim: {str(exc)}",
        )


@router.post(
    "/{claim_id}/withdraw",
    response_model=dict,
    summary="Withdraw claim",
    description="Employee withdraws their own submitted claim.",
)
async def withdraw_claim(
    claim_id: str,
    request: WithdrawClaimRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Withdraw own claim.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.withdraw_claim(
            claim_id=claim_id,
            employee_id=employee_id,
            request=request,
            company_id=company_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to withdraw claim: {str(exc)}",
        )


# -------------------------
# Attachment endpoints
# -------------------------


@router.post(
    "/{claim_id}/attachments",
    response_model=dict,
    summary="Add claim attachment",
    description="Add bill/receipt attachment metadata to claim.",
)
async def add_claim_attachment(
    claim_id: str,
    request: AddClaimAttachmentRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Add claim attachment metadata.

    This endpoint saves metadata only.
    Actual file upload should happen through storage service first.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        success, result = await service.add_attachment(
            claim_id=claim_id,
            employee_id=employee_id,
            request=request,
            company_id=company_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add claim attachment: {str(exc)}",
        )


@router.post(
    "/{claim_id}/attachments/{attachment_index}/verify",
    response_model=dict,
    summary="Verify claim attachment",
    description="HR/Admin verifies uploaded claim attachment.",
    dependencies=[Depends(require_hr)],
)
async def verify_claim_attachment(
    claim_id: str,
    attachment_index: int,
    request: VerifyClaimAttachmentRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Verify or unverify claim attachment.
    """
    try:
        verifier_id = get_current_employee_id(current_user)

        success, result = await service.verify_attachment(
            claim_id=claim_id,
            attachment_index=attachment_index,
            verifier_id=verifier_id,
            request=request,
            company_id=company_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to verify claim attachment: {str(exc)}",
        )


# -------------------------
# Payment endpoints
# -------------------------


@router.post(
    "/{claim_id}/payment/start",
    response_model=dict,
    summary="Start payment processing",
    description="Move approved claim to payment processing. HR/Admin only.",
    dependencies=[Depends(require_hr)],
)
async def start_payment_processing(
    claim_id: str,
    request: StartClaimPaymentProcessingRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Start payment processing for approved claim.
    """
    try:
        actor_id = get_current_employee_id(current_user)

        success, result = await service.start_payment_processing(
            claim_id=claim_id,
            actor_id=actor_id,
            request=request,
            company_id=company_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start payment processing: {str(exc)}",
        )


@router.post(
    "/{claim_id}/payment/paid",
    response_model=dict,
    summary="Mark claim paid",
    description="Mark claim reimbursement as paid. HR/Admin only.",
    dependencies=[Depends(require_hr)],
)
async def mark_claim_paid(
    claim_id: str,
    request: MarkClaimPaidRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Mark claim as paid.
    """
    try:
        actor_id = get_current_employee_id(current_user)

        success, result = await service.mark_claim_paid(
            claim_id=claim_id,
            actor_id=actor_id,
            request=request,
            company_id=company_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark claim paid: {str(exc)}",
        )


@router.post(
    "/{claim_id}/payment/failed",
    response_model=dict,
    summary="Mark claim payment failed",
    description="Mark claim reimbursement payment as failed. HR/Admin only.",
    dependencies=[Depends(require_hr)],
)
async def mark_payment_failed(
    claim_id: str,
    request: MarkClaimPaymentFailedRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Mark claim payment as failed.
    """
    try:
        actor_id = get_current_employee_id(current_user)

        success, result = await service.mark_payment_failed(
            claim_id=claim_id,
            actor_id=actor_id,
            request=request,
            company_id=company_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark claim payment failed: {str(exc)}",
        )


@router.patch(
    "/{claim_id}/payment/status",
    response_model=dict,
    summary="Update payment status",
    description="Generic payment status update. Prefer specific payment endpoints.",
    dependencies=[Depends(require_hr)],
)
async def update_payment_status(
    claim_id: str,
    request: UpdatePaymentStatusRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Generic payment status update.

    Prefer specific endpoints:
    - /payment/start
    - /payment/paid
    - /payment/failed
    """
    try:
        actor_id = get_current_employee_id(current_user)

        success, result = await service.update_payment_status(
            claim_id=claim_id,
            actor_id=actor_id,
            request=request,
            company_id=company_id,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update payment status: {str(exc)}",
        )


# -------------------------
# HR/Admin dashboard endpoints
# -------------------------


@router.get(
    "/dashboard/statistics",
    response_model=dict,
    summary="Get claim dashboard statistics",
    description="HR/Admin dashboard statistics for claim module.",
    dependencies=[Depends(require_hr)],
)
async def get_claim_dashboard_statistics(
    company_id: str = Query(default="default"),
    from_date: Optional[Date] = Query(default=None),
    to_date: Optional[Date] = Query(default=None),
    department_id: Optional[str] = Query(default=None),
    manager_id: Optional[str] = Query(default=None),
    claim_type_id: Optional[str] = Query(default=None),
    currency: str = Query(default="INR", min_length=3, max_length=3),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Get company-wide claim dashboard statistics.
    """
    try:
        filters = ClaimDashboardFilters(
            company_id=company_id,
            from_date=from_date,
            to_date=to_date,
            department_id=department_id,
            manager_id=manager_id,
            claim_type_id=claim_type_id,
            currency=currency,
        )

        success, result = await service.get_dashboard(filters=filters)

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get claim dashboard statistics: {str(exc)}",
        )


# -------------------------
# Get by claim ID
# Keep this near bottom to avoid route confusion.
# -------------------------


@router.get(
    "/{claim_id}",
    response_model=dict,
    summary="Get claim by ID",
    description="Get detailed information for a specific claim.",
)
async def get_claim_by_id(
    claim_id: str,
    company_id: str = Query(default="default"),
    private: bool = Query(default=False),
    current_user: dict = Depends(get_current_active_user),
    service: ClaimService = Depends(get_claim_service),
):
    """
    Get claim by claim_id, for example CLM-2026-0001.

    Access control:
    - Employees can view own claims only.
    - Managers can view team claims.
    - HR/Admin can view all/private fields.
    """
    try:
        success, result = await service.get_claim_by_id(
            claim_id=claim_id,
            requesting_employee_id=current_user.get("employee_id"),
            is_manager=is_manager_user(current_user),
            is_hr=is_hr_user(current_user),
            is_admin=is_admin_user(current_user),
            is_finance=is_finance_user(current_user),
            company_id=company_id,
            private=private,
        )

        if not success:
            raise_service_error(result)

        return unwrap_service_result(result)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get claim: {str(exc)}",
        )