"""
Leave routes - API endpoints for leave management.

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

Production/MVP note:
- In MVP/local mode, MongoDB acts as mock HRMS.
- In production HRMS read-only mode, write routes should be disabled by service
  or routed to approved HRMS/company workflow APIs.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.app.database.mongo_connection import get_database
from backend.app.dependencies.auth_dependencies import (
    get_current_active_user,
    require_hr,
    require_manager,
)
from backend.app.models.leave_model import (
    LeaveRejectionReason,
    LeaveSource,
    LeaveStatus,
)
from backend.app.repositories.employee_repository import EmployeeRepository
from backend.app.repositories.holiday_repository import HolidayRepository
from backend.app.repositories.leave_repository import LeaveRepository
from backend.app.repositories.leave_type_repository import LeaveTypeRepository
from backend.app.schemas.leave_schema import (
    AddLeaveAttachmentRequest,
    ApproveLeaveRequest,
    CancelLeaveRequest,
    CreateLeaveForEmployeeRequest,
    CreateLeaveRequestRequest,
    ImportHRMSLeaveRecordRequest,
    LeaveActionResponse,
    LeaveAttachmentResponse,
    LeaveBalanceResponse,
    LeaveCalendarResponse,
    LeaveDashboardStatisticsResponse,
    LeaveFilterParams,
    LeaveModuleCapabilitiesResponse,
    LeavePendingApprovalsResponse,
    LeaveRequestCreatedResponse,
    LeaveRequestListResponse,
    LeaveRequestPrivateResponse,
    LeaveRequestResponse,
    LeaveRequestSummaryResponse,
    LeaveRequestUpdatedResponse,
    LeaveStatisticsResponse,
    LeaveTypeStatisticsResponse,
    RejectLeaveRequest,
    UpdateLeaveRequestRequest,
    VerifyLeaveAttachmentRequest,
    WithdrawLeaveRequest,
)
from backend.app.services.leave_service import LeaveService

router = APIRouter(prefix="/leaves", tags=["Leave Management"])


# -------------------------
# Dependency helpers
# -------------------------


def get_leave_service(db: AsyncIOMotorDatabase = Depends(get_database)) -> LeaveService:
    """
    Get leave service instance.

    For now mode is local_mvp.
    Later this can come from settings:
        LEAVE_MODE=local_mvp
        LEAVE_MODE=hrms_readonly
        LEAVE_MODE=hrms_write_approved
    """
    leave_repo = LeaveRepository(db)
    employee_repo = EmployeeRepository(db)
    leave_type_repo = LeaveTypeRepository(db)
    holiday_repo = HolidayRepository(db)

    return LeaveService(
        leave_repo=leave_repo,
        employee_repo=employee_repo,
        leave_type_repo=leave_type_repo,
        holiday_repo=holiday_repo,
        mode="local_mvp",
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

    return employee_id


def get_current_user_role(current_user: dict) -> str:
    """
    Normalize user role from current user.
    """
    role = current_user.get("role", "")

    if hasattr(role, "value"):
        role = role.value

    return str(role).strip().lower()


def ensure_leave_access(leave: dict, current_user: dict) -> None:
    """
    Check whether current user can view the leave request.

    Allowed:
    - HR/Admin
    - leave owner
    - current approver
    - manager from leave snapshot
    """
    employee_id = current_user.get("employee_id")
    user_role = get_current_user_role(current_user)

    if user_role in {"hr", "admin"}:
        return

    if leave.get("employee_id") == employee_id:
        return

    if leave.get("current_approver_id") == employee_id:
        return

    if leave.get("manager_id") == employee_id:
        return

    raise HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this leave request",
    )


def to_summary_list(leaves: List[dict]) -> List[LeaveRequestSummaryResponse]:
    """
    Convert leave documents to summary responses.
    """
    return [LeaveRequestSummaryResponse(**leave) for leave in leaves]


# -------------------------
# Capability endpoint
# -------------------------


@router.get(
    "/capabilities",
    response_model=LeaveModuleCapabilitiesResponse,
    summary="Get leave module capabilities",
    description="Shows what leave actions are enabled in current deployment mode.",
)
async def get_leave_capabilities(
    service: LeaveService = Depends(get_leave_service),
):
    """
    Get leave module capabilities.
    """
    return LeaveModuleCapabilitiesResponse(**service.get_capabilities())


# -------------------------
# Create leave request
# -------------------------


@router.post(
    "",
    response_model=LeaveRequestCreatedResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="Create leave request",
    description="Employee creates a new leave request. Leave goes to approval workflow.",
)
async def create_leave_request(
    request: CreateLeaveRequestRequest,
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Create leave request for logged-in employee.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        leave = await service.create_leave_request(
            employee_id=employee_id,
            leave_type_id=request.leave_type_id,
            start_date=request.start_date,
            end_date=request.end_date,
            reason=request.reason,
            contact_during_leave=request.contact_during_leave,
            handover_notes=request.handover_notes,
            half_day_dates=request.half_day_dates,
            half_day_types=request.half_day_types,
            is_emergency=request.is_emergency,
            created_by=employee_id,
            company_id=request.company_id,
        )

        return LeaveRequestCreatedResponse(
            message="Leave request created successfully",
            leave_id=leave["id"],
            leave_request_id=leave["leave_request_id"],
            status=LeaveStatus(leave["status"]),
            leave=LeaveRequestResponse(**leave),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create leave request: {str(exc)}",
        )


@router.post(
    "/employee/{employee_id}",
    response_model=LeaveRequestCreatedResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="Create leave for employee",
    description="HR/Admin creates a leave request on behalf of an employee.",
    dependencies=[Depends(require_hr)],
)
async def create_leave_for_employee(
    employee_id: str,
    request: CreateLeaveForEmployeeRequest,
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    HR/Admin creates leave request for a specific employee.
    """
    try:
        created_by = current_user.get("employee_id") or current_user.get("id") or "system"

        leave = await service.create_leave_request(
            employee_id=employee_id,
            leave_type_id=request.leave_type_id,
            start_date=request.start_date,
            end_date=request.end_date,
            reason=request.reason,
            contact_during_leave=request.contact_during_leave,
            handover_notes=request.handover_notes,
            half_day_dates=request.half_day_dates,
            half_day_types=request.half_day_types,
            is_emergency=request.is_emergency,
            created_by=created_by,
            company_id=request.company_id,
        )

        return LeaveRequestCreatedResponse(
            message="Leave request created successfully",
            leave_id=leave["id"],
            leave_request_id=leave["leave_request_id"],
            status=LeaveStatus(leave["status"]),
            leave=LeaveRequestResponse(**leave),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create leave for employee: {str(exc)}",
        )


# -------------------------
# My leave endpoints
# -------------------------


@router.get(
    "/me",
    response_model=LeaveRequestListResponse,
    summary="Get my leave requests",
    description="Get leave requests for logged-in employee.",
)
async def get_my_leaves(
    company_id: str = Query(default="default"),
    leave_status: Optional[LeaveStatus] = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Get leave requests for logged-in employee.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        status_value = leave_status.value if leave_status else None

        leaves, total = await service.list_employee_leaves(
            employee_id=employee_id,
            company_id=company_id,
            status=status_value,
            skip=skip,
            limit=limit,
        )

        return LeaveRequestListResponse(
            leaves=to_summary_list(leaves),
            total=total,
            skip=skip,
            limit=limit,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get leaves: {str(exc)}",
        )


@router.get(
    "/me/statistics",
    response_model=LeaveStatisticsResponse,
    summary="Get my leave statistics",
    description="Get leave statistics for logged-in employee.",
)
async def get_my_leave_statistics(
    company_id: str = Query(default="default"),
    year: Optional[int] = Query(default=None),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Get leave statistics for logged-in employee.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        stats = await service.get_leave_statistics(
            employee_id=employee_id,
            company_id=company_id,
            year=year,
        )

        return LeaveStatisticsResponse(**stats)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get statistics: {str(exc)}",
        )


@router.get(
    "/me/upcoming",
    response_model=List[LeaveRequestSummaryResponse],
    summary="Get my upcoming leaves",
    description="Get upcoming approved leaves for logged-in employee.",
)
async def get_my_upcoming_leaves(
    company_id: str = Query(default="default"),
    limit: int = Query(default=5, ge=1, le=20),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Get upcoming approved leaves.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        leaves = await service.get_upcoming_leaves(
            employee_id=employee_id,
            company_id=company_id,
            limit=limit,
        )

        return to_summary_list(leaves)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get upcoming leaves: {str(exc)}",
        )


@router.get(
    "/me/balance/{leave_type_code}",
    response_model=LeaveBalanceResponse,
    summary="Get my leave balance",
    description="Get logged-in employee leave balance for a leave type.",
)
async def get_my_leave_balance(
    leave_type_code: str,
    company_id: str = Query(default="default"),
    year: Optional[int] = Query(default=None),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Get leave balance for logged-in employee.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        balance = await service.get_leave_balance(
            employee_id=employee_id,
            leave_type_code=leave_type_code,
            company_id=company_id,
            year=year,
        )

        return LeaveBalanceResponse(**balance)

    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get leave balance: {str(exc)}",
        )


# -------------------------
# List/search/filter endpoints
# -------------------------


@router.get(
    "",
    response_model=LeaveRequestListResponse,
    summary="List leave requests",
    description="List/filter leave requests. HR/Admin can view all. Normal users see their own unless filtered through allowed access.",
    dependencies=[Depends(require_hr)],
)
async def list_leaves(
    company_id: str = Query(default="default"),
    employee_id: Optional[str] = Query(default=None),
    employee_code: Optional[str] = Query(default=None),
    leave_status: Optional[LeaveStatus] = Query(default=None, alias="status"),
    leave_type_id: Optional[str] = Query(default=None),
    leave_type_code: Optional[str] = Query(default=None),
    department_id: Optional[str] = Query(default=None),
    manager_id: Optional[str] = Query(default=None),
    current_approver_id: Optional[str] = Query(default=None),
    source: Optional[LeaveSource] = Query(default=None),
    is_read_only: Optional[bool] = Query(default=None),
    start_date_from: Optional[date] = Query(default=None),
    start_date_to: Optional[date] = Query(default=None),
    applied_date_from: Optional[date] = Query(default=None),
    applied_date_to: Optional[date] = Query(default=None),
    is_emergency: Optional[bool] = Query(default=None),
    is_backdated: Optional[bool] = Query(default=None),
    is_half_day: Optional[bool] = Query(default=None),
    has_conflict: Optional[bool] = Query(default=None),
    documentation_required: Optional[bool] = Query(default=None),
    documentation_received: Optional[bool] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=100),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    sort_by: str = Query(default="applied_date"),
    sort_order: str = Query(default="desc"),
    service: LeaveService = Depends(get_leave_service),
):
    """
    List leave requests with filters.
    """
    try:
        leaves, total = await service.list_leaves_with_filters(
            company_id=company_id,
            employee_id=employee_id,
            employee_code=employee_code,
            status=leave_status.value if leave_status else None,
            leave_type_id=leave_type_id,
            leave_type_code=leave_type_code,
            department_id=department_id,
            manager_id=manager_id,
            current_approver_id=current_approver_id,
            source=source.value if source else None,
            is_read_only=is_read_only,
            start_date_from=start_date_from,
            start_date_to=start_date_to,
            applied_date_from=applied_date_from,
            applied_date_to=applied_date_to,
            is_emergency=is_emergency,
            is_backdated=is_backdated,
            is_half_day=is_half_day,
            has_conflict=has_conflict,
            documentation_required=documentation_required,
            documentation_received=documentation_received,
            search=search,
            skip=skip,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        return LeaveRequestListResponse(
            leaves=to_summary_list(leaves),
            total=total,
            skip=skip,
            limit=limit,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list leaves: {str(exc)}",
        )


@router.post(
    "/filter",
    response_model=LeaveRequestListResponse,
    summary="Filter leave requests",
    description="Advanced filter endpoint using request body.",
    dependencies=[Depends(require_hr)],
)
async def filter_leaves(
    filters: LeaveFilterParams,
    service: LeaveService = Depends(get_leave_service),
):
    """
    Filter leave requests using body payload.
    """
    try:
        leaves, total = await service.list_leaves_with_filters(
            company_id=filters.company_id,
            employee_id=filters.employee_id,
            employee_code=filters.employee_code,
            status=filters.status.value if filters.status else None,
            statuses=[item.value for item in filters.statuses] if filters.statuses else None,
            leave_type_id=filters.leave_type_id,
            leave_type_code=filters.leave_type_code,
            department_id=filters.department_id,
            manager_id=filters.manager_id,
            current_approver_id=filters.current_approver_id,
            source=filters.source.value if filters.source else None,
            is_read_only=filters.is_read_only,
            start_date_from=filters.start_date_from,
            start_date_to=filters.start_date_to,
            applied_date_from=filters.applied_date_from,
            applied_date_to=filters.applied_date_to,
            is_emergency=filters.is_emergency,
            is_backdated=filters.is_backdated,
            is_half_day=filters.is_half_day,
            has_conflict=filters.has_conflict,
            documentation_required=filters.documentation_required,
            documentation_received=filters.documentation_received,
            search=filters.search,
            skip=filters.skip,
            limit=filters.limit,
            sort_by=filters.sort_by,
            sort_order=filters.sort_order,
        )

        return LeaveRequestListResponse(
            leaves=to_summary_list(leaves),
            total=total,
            skip=filters.skip,
            limit=filters.limit,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to filter leaves: {str(exc)}",
        )


# -------------------------
# Approval endpoints
# -------------------------


@router.get(
    "/pending-approvals",
    response_model=LeavePendingApprovalsResponse,
    summary="Get pending approvals",
    description="Get leaves pending approval for current manager/HR user.",
    dependencies=[Depends(require_manager)],
)
async def get_pending_approvals(
    company_id: str = Query(default="default"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Get leaves pending approval for logged-in manager/HR.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        leaves, total = await service.list_pending_approvals(
            approver_id=employee_id,
            company_id=company_id,
            skip=skip,
            limit=limit,
        )

        return LeavePendingApprovalsResponse(
            leaves=to_summary_list(leaves),
            total=total,
            skip=skip,
            limit=limit,
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get pending approvals: {str(exc)}",
        )


@router.post(
    "/{leave_id}/approve",
    response_model=LeaveActionResponse,
    summary="Approve leave request",
    description="Manager/HR approves leave request.",
    dependencies=[Depends(require_manager)],
)
async def approve_leave(
    leave_id: str,
    request: ApproveLeaveRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Approve leave request.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        leave = await service.approve_leave(
            leave_id=leave_id,
            approver_id=employee_id,
            comments=request.comments,
            company_id=company_id,
        )

        return LeaveActionResponse(
            message="Leave request approved successfully",
            leave_request_id=leave["leave_request_id"],
            status=LeaveStatus(leave["status"]),
            action_date=leave["updated_at"],
            leave=LeaveRequestResponse(**leave),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to approve leave: {str(exc)}",
        )


@router.post(
    "/{leave_id}/reject",
    response_model=LeaveActionResponse,
    summary="Reject leave request",
    description="Manager/HR rejects leave request.",
    dependencies=[Depends(require_manager)],
)
async def reject_leave(
    leave_id: str,
    request: RejectLeaveRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Reject leave request.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        leave = await service.reject_leave(
            leave_id=leave_id,
            approver_id=employee_id,
            rejection_reason=request.rejection_reason,
            comments=request.comments,
            company_id=company_id,
        )

        return LeaveActionResponse(
            message="Leave request rejected",
            leave_request_id=leave["leave_request_id"],
            status=LeaveStatus(leave["status"]),
            action_date=leave["updated_at"],
            leave=LeaveRequestResponse(**leave),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reject leave: {str(exc)}",
        )


# -------------------------
# Update / cancel / withdraw endpoints
# -------------------------


@router.patch(
    "/{leave_id}",
    response_model=LeaveRequestUpdatedResponse,
    summary="Update leave request",
    description="Update draft or pending leave request.",
)
async def update_leave_request(
    leave_id: str,
    request: UpdateLeaveRequestRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Update leave request.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        leave = await service.update_leave_request(
            leave_id=leave_id,
            employee_id=employee_id,
            update_data=request.model_dump(exclude_unset=True),
            company_id=company_id,
        )

        return LeaveRequestUpdatedResponse(
            message="Leave request updated successfully",
            leave_request_id=leave["leave_request_id"],
            updated_at=leave["updated_at"],
            leave=LeaveRequestResponse(**leave),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update leave: {str(exc)}",
        )


@router.post(
    "/{leave_id}/cancel",
    response_model=LeaveActionResponse,
    summary="Cancel leave request",
    description="Employee cancels their own leave request.",
)
async def cancel_leave(
    leave_id: str,
    request: CancelLeaveRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Cancel leave request.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        leave = await service.cancel_leave(
            leave_id=leave_id,
            employee_id=employee_id,
            cancellation_reason=request.cancellation_reason,
            company_id=company_id,
        )

        return LeaveActionResponse(
            message="Leave request cancelled successfully",
            leave_request_id=leave["leave_request_id"],
            status=LeaveStatus(leave["status"]),
            action_date=leave["updated_at"],
            leave=LeaveRequestResponse(**leave),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel leave: {str(exc)}",
        )


@router.post(
    "/{leave_id}/withdraw",
    response_model=LeaveActionResponse,
    summary="Withdraw approved leave",
    description="Employee withdraws an approved future leave request.",
)
async def withdraw_leave(
    leave_id: str,
    request: WithdrawLeaveRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Withdraw approved leave.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        leave = await service.withdraw_leave(
            leave_id=leave_id,
            employee_id=employee_id,
            withdrawal_reason=request.withdrawal_reason,
            company_id=company_id,
        )

        return LeaveActionResponse(
            message="Leave request withdrawn successfully",
            leave_request_id=leave["leave_request_id"],
            status=LeaveStatus(leave["status"]),
            action_date=leave["updated_at"],
            leave=LeaveRequestResponse(**leave),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to withdraw leave: {str(exc)}",
        )


# -------------------------
# Attachment endpoints
# -------------------------


@router.post(
    "/{leave_id}/attachments",
    response_model=LeaveAttachmentResponse,
    summary="Add leave attachment",
    description="Add attachment metadata to leave request.",
)
async def add_leave_attachment(
    leave_id: str,
    request: AddLeaveAttachmentRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Add leave attachment metadata.
    """
    try:
        employee_id = get_current_employee_id(current_user)

        leave = await service.add_attachment(
            leave_id=leave_id,
            attachment_data=request.model_dump(),
            uploaded_by=employee_id,
            company_id=company_id,
        )

        return LeaveAttachmentResponse(
            message="Attachment added successfully",
            leave_request_id=leave["leave_request_id"],
            attachments=leave.get("attachments", []),
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add attachment: {str(exc)}",
        )


@router.patch(
    "/{leave_id}/attachments/verify",
    response_model=LeaveAttachmentResponse,
    summary="Verify leave attachment",
    description="HR/Admin verifies uploaded leave attachment.",
    dependencies=[Depends(require_hr)],
)
async def verify_leave_attachment(
    leave_id: str,
    request: VerifyLeaveAttachmentRequest,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Placeholder for attachment verification.

    Service method can be added later if needed.
    """
    raise HTTPException(
        status_code=http_status.HTTP_501_NOT_IMPLEMENTED,
        detail="Attachment verification service is not implemented yet",
    )


# -------------------------
# HR/Admin endpoints
# -------------------------


@router.get(
    "/employee/{employee_id}",
    response_model=LeaveRequestListResponse,
    summary="Get employee leaves",
    description="HR/Admin can view any employee's leaves.",
    dependencies=[Depends(require_hr)],
)
async def get_employee_leaves(
    employee_id: str,
    company_id: str = Query(default="default"),
    leave_status: Optional[LeaveStatus] = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Get leaves for specific employee.
    """
    try:
        leaves, total = await service.list_employee_leaves(
            employee_id=employee_id,
            company_id=company_id,
            status=leave_status.value if leave_status else None,
            skip=skip,
            limit=limit,
        )

        return LeaveRequestListResponse(
            leaves=to_summary_list(leaves),
            total=total,
            skip=skip,
            limit=limit,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get employee leaves: {str(exc)}",
        )


@router.get(
    "/employee/{employee_id}/statistics",
    response_model=LeaveStatisticsResponse,
    summary="Get employee leave statistics",
    description="HR/Admin can view any employee's leave statistics.",
    dependencies=[Depends(require_hr)],
)
async def get_employee_statistics(
    employee_id: str,
    company_id: str = Query(default="default"),
    year: Optional[int] = Query(default=None),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Get leave statistics for specific employee.
    """
    try:
        stats = await service.get_leave_statistics(
            employee_id=employee_id,
            company_id=company_id,
            year=year,
        )

        return LeaveStatisticsResponse(**stats)

    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get statistics: {str(exc)}",
        )


@router.get(
    "/dashboard/statistics",
    response_model=LeaveDashboardStatisticsResponse,
    summary="Get leave dashboard statistics",
    description="HR/Admin dashboard statistics for leave module.",
    dependencies=[Depends(require_hr)],
)
async def get_leave_dashboard_statistics(
    company_id: str = Query(default="default"),
    year: Optional[int] = Query(default=None),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Get company-wide leave statistics.
    """
    try:
        stats = await service.get_dashboard_statistics(
            company_id=company_id,
            year=year,
        )

        return LeaveDashboardStatisticsResponse(**stats)

    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get dashboard statistics: {str(exc)}",
        )


@router.get(
    "/statistics/by-leave-type",
    response_model=List[LeaveTypeStatisticsResponse],
    summary="Get statistics by leave type",
    description="HR/Admin leave statistics grouped by leave type.",
    dependencies=[Depends(require_hr)],
)
async def get_statistics_by_leave_type(
    company_id: str = Query(default="default"),
    year: Optional[int] = Query(default=None),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Get leave statistics grouped by leave type.
    """
    try:
        stats = await service.get_statistics_by_leave_type(
            company_id=company_id,
            year=year,
        )

        return [
            LeaveTypeStatisticsResponse(
                leave_type_code=str(item.get("_id")),
                leave_type_name=item.get("leave_type_name"),
                request_count=item.get("request_count", 0),
                approved_count=item.get("approved_count", 0),
                approved_days=item.get("approved_days", 0.0),
            )
            for item in stats
        ]

    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get leave type statistics: {str(exc)}",
        )


@router.get(
    "/calendar",
    response_model=LeaveCalendarResponse,
    summary="Get leave calendar",
    description="Get leave records for calendar view.",
    dependencies=[Depends(require_manager)],
)
async def get_leave_calendar(
    company_id: str = Query(default="default"),
    start_date: date = Query(...),
    end_date: date = Query(...),
    department_id: Optional[str] = Query(default=None),
    manager_id: Optional[str] = Query(default=None),
    include_pending: bool = Query(default=True),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Get leave calendar data.
    """
    try:
        if end_date < start_date:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="end_date cannot be before start_date",
            )

        leaves = await service.get_calendar_leaves(
            start_date=start_date,
            end_date=end_date,
            company_id=company_id,
            department_id=department_id,
            manager_id=manager_id,
            include_pending=include_pending,
        )

        return LeaveCalendarResponse(
            company_id=company_id,
            start_date=start_date,
            end_date=end_date,
            days=[],
            leaves=to_summary_list(leaves),
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get leave calendar: {str(exc)}",
        )


# -------------------------
# HRMS/import endpoint
# -------------------------


@router.post(
    "/import/hrms",
    response_model=LeaveRequestPrivateResponse,
    status_code=http_status.HTTP_201_CREATED,
    summary="Import HRMS leave record",
    description="Import a read-only HRMS leave record. Admin only.",
    dependencies=[Depends(require_hr)],
)
async def import_hrms_leave_record(
    request: ImportHRMSLeaveRecordRequest,
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Import HRMS leave record as read-only.
    """
    try:
        imported_by = (
            current_user.get("employee_id")
            or current_user.get("id")
            or current_user.get("_id")
            or "system"
        )

        leave = await service.import_hrms_leave_record(
            leave_data=request.model_dump(),
            imported_by=str(imported_by),
        )

        return LeaveRequestPrivateResponse(**leave)

    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import HRMS leave record: {str(exc)}",
        )


# -------------------------
# Get by request ID / Mongo ID
# Keep these near bottom to avoid route confusion.
# -------------------------


@router.get(
    "/request/{leave_request_id}",
    response_model=LeaveRequestResponse,
    summary="Get leave by request ID",
    description="Get leave request by leave_request_id, for example LV-2026-0001.",
)
async def get_leave_by_request_id(
    leave_request_id: str,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Get leave request by leave_request_id.
    """
    try:
        leave = await service.get_leave_by_request_id(
            leave_request_id,
            company_id,
        )

        if not leave:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Leave request {leave_request_id} not found",
            )

        ensure_leave_access(leave, current_user)

        return LeaveRequestResponse(**leave)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get leave: {str(exc)}",
        )


@router.get(
    "/{leave_id}",
    response_model=LeaveRequestResponse,
    summary="Get leave request by ID",
    description="Get detailed leave request information.",
)
async def get_leave_by_id(
    leave_id: str,
    company_id: str = Query(default="default"),
    current_user: dict = Depends(get_current_active_user),
    service: LeaveService = Depends(get_leave_service),
):
    """
    Get leave request by MongoDB ID.
    """
    try:
        leave = await service.get_leave_by_id(leave_id, company_id)

        if not leave:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Leave request not found",
            )

        ensure_leave_access(leave, current_user)

        return LeaveRequestResponse(**leave)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get leave: {str(exc)}",
        )