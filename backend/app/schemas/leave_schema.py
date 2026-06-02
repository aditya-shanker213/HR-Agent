"""
Leave schemas - Request/Response models for Leave API endpoints.

This file contains Pydantic schemas for:
- Creating leave requests
- Updating leave requests
- Approving/rejecting leaves
- Cancelling/withdrawing leaves
- Leave responses
- Leave filters and search
- Leave statistics
- Leave calendar responses

Pattern:
- Request schemas validate API input
- Response schemas define safe API output
- Model file defines MongoDB document structure
- Repository handles MongoDB operations only
- Service handles business validation

Production/MVP note:
- In MVP/local mode, MongoDB acts as mock HRMS.
- In production HRMS read-only mode, create/update/write routes should be disabled
  or routed to approved company workflow APIs.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.models.leave_model import (
    LeaveApprovalStep,
    LeaveAttachment,
    LeaveBalanceAction,
    LeaveDashboardStatistics,
    LeaveDay,
    LeaveDayType,
    LeaveRejectionReason,
    LeaveRequestPrivateResponse,
    LeaveRequestResponse as LeaveModelResponse,
    LeaveRequestSummary,
    LeaveSource,
    LeaveStatus,
)


# -------------------------
# Shared helpers
# -------------------------


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    """
    Strip optional text fields.

    Empty string becomes None.
    """
    if value is None:
        return None

    value = str(value).strip()
    return value or None


def normalize_required_text(value: str, field_name: str) -> str:
    """
    Strip required text fields.
    """
    value = str(value).strip()

    if not value:
        raise ValueError(f"{field_name} cannot be empty")

    return value


def normalize_company_id(value: Optional[str]) -> str:
    """
    Normalize company_id.
    """
    if value is None:
        return "default"

    value = str(value).strip().lower()

    if not value:
        return "default"

    if not value.replace("_", "").replace("-", "").isalnum():
        raise ValueError(
            "company_id can contain only letters, numbers, hyphen, and underscore"
        )

    return value


def normalize_code(value: Optional[str]) -> Optional[str]:
    """
    Normalize code fields.
    """
    if value is None:
        return None

    value = str(value).strip().upper()
    return value or None


# -------------------------
# Request Schemas
# -------------------------


class CreateLeaveRequestRequest(BaseModel):
    """
    Request schema for creating a new leave request.

    Employee identity should normally come from logged-in user context.
    Do not trust employee_id from public request body unless HR/Admin route uses it.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    company_id: str = Field(
        default="default",
        min_length=2,
        max_length=100,
        description="Company identifier",
    )

    leave_type_id: str = Field(
        ...,
        min_length=1,
        description="Reference to leave_types._id",
    )

    start_date: date = Field(..., description="Leave start date")
    end_date: date = Field(..., description="Leave end date")

    reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Reason for leave",
    )

    contact_during_leave: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Contact phone/email during leave",
    )

    handover_notes: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Work handover notes",
    )

    half_day_dates: Optional[List[date]] = Field(
        default=None,
        description="Dates where half-day leave is needed",
    )

    half_day_types: Optional[List[LeaveDayType]] = Field(
        default=None,
        description="Half-day type for each half-day date",
    )

    is_emergency: bool = Field(
        default=False,
        description="Is this an emergency leave",
    )

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)

    @field_validator("leave_type_id", "contact_during_leave", "handover_notes")
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = normalize_required_text(value, "reason")

        if len(value) < 10:
            raise ValueError("reason must be at least 10 characters")

        return value

    @model_validator(mode="after")
    def validate_dates(self):
        """
        Validate leave dates and half-day configuration.
        """
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")

        if self.half_day_dates and self.half_day_types:
            if len(self.half_day_dates) != len(self.half_day_types):
                raise ValueError("half_day_dates and half_day_types must have same length")

            if len(self.half_day_dates) != len(set(self.half_day_dates)):
                raise ValueError("half_day_dates cannot contain duplicate dates")

            for half_day_date in self.half_day_dates:
                if not (self.start_date <= half_day_date <= self.end_date):
                    raise ValueError(
                        f"Half-day date {half_day_date} is outside leave range"
                    )

        elif self.half_day_dates or self.half_day_types:
            raise ValueError("Both half_day_dates and half_day_types must be provided together")

        return self


class CreateLeaveForEmployeeRequest(CreateLeaveRequestRequest):
    """
    HR/Admin request schema for creating leave on behalf of an employee.
    """

    employee_id: str = Field(
        ...,
        min_length=1,
        description="Employee ID for whom leave is being created",
    )

    @field_validator("employee_id")
    @classmethod
    def clean_employee_id(cls, value: str) -> str:
        return normalize_required_text(value, "employee_id")


class UpdateLeaveRequestRequest(BaseModel):
    """
    Request schema for updating a draft or pending leave request.

    Service layer decides which statuses are editable.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    leave_type_id: Optional[str] = Field(default=None, min_length=1)
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    reason: Optional[str] = Field(default=None, min_length=10, max_length=1000)
    contact_during_leave: Optional[str] = Field(default=None, max_length=100)
    handover_notes: Optional[str] = Field(default=None, max_length=1000)

    half_day_dates: Optional[List[date]] = None
    half_day_types: Optional[List[LeaveDayType]] = None

    is_emergency: Optional[bool] = None

    @field_validator("leave_type_id", "contact_during_leave", "handover_notes")
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        value = normalize_required_text(value, "reason")

        if len(value) < 10:
            raise ValueError("reason must be at least 10 characters")

        return value

    @model_validator(mode="after")
    def validate_at_least_one_field(self):
        """
        Prevent empty update payload.
        """
        values = self.model_dump(exclude_unset=True)

        if not values:
            raise ValueError("At least one field must be provided for update")

        return self

    @model_validator(mode="after")
    def validate_dates(self):
        """
        Validate date and half-day configuration.
        """
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValueError("end_date cannot be before start_date")

        if self.half_day_dates and self.half_day_types:
            if len(self.half_day_dates) != len(self.half_day_types):
                raise ValueError("half_day_dates and half_day_types must have same length")

            if len(self.half_day_dates) != len(set(self.half_day_dates)):
                raise ValueError("half_day_dates cannot contain duplicate dates")

            if self.start_date and self.end_date:
                for half_day_date in self.half_day_dates:
                    if not (self.start_date <= half_day_date <= self.end_date):
                        raise ValueError(
                            f"Half-day date {half_day_date} is outside leave range"
                        )

        elif self.half_day_dates or self.half_day_types:
            raise ValueError("Both half_day_dates and half_day_types must be provided together")

        return self


class SubmitDraftLeaveRequest(BaseModel):
    """
    Request schema for submitting a draft leave.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    confirmation: bool = Field(
        default=True,
        description="User confirmation to submit leave request",
    )


class ApproveLeaveRequest(BaseModel):
    """
    Request schema for approving leave.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    comments: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Approval comments",
    )

    @field_validator("comments")
    @classmethod
    def clean_comments(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class RejectLeaveRequest(BaseModel):
    """
    Request schema for rejecting leave.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    rejection_reason: LeaveRejectionReason = Field(
        ...,
        description="Reason for rejection",
    )

    comments: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Rejection comments",
    )

    @field_validator("comments")
    @classmethod
    def validate_comments(cls, value: str) -> str:
        value = normalize_required_text(value, "comments")

        if len(value) < 10:
            raise ValueError("comments must be at least 10 characters")

        return value


class CancelLeaveRequest(BaseModel):
    """
    Request schema for cancelling leave before approval/start date.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    cancellation_reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Reason for cancellation",
    )

    @field_validator("cancellation_reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = normalize_required_text(value, "cancellation_reason")

        if len(value) < 10:
            raise ValueError("cancellation_reason must be at least 10 characters")

        return value


class WithdrawLeaveRequest(BaseModel):
    """
    Request schema for withdrawing an already approved leave.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    withdrawal_reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Reason for withdrawal",
    )

    @field_validator("withdrawal_reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = normalize_required_text(value, "withdrawal_reason")

        if len(value) < 10:
            raise ValueError("withdrawal_reason must be at least 10 characters")

        return value


class AddLeaveAttachmentRequest(BaseModel):
    """
    Request schema for adding attachment metadata to leave.

    Actual file upload should be handled by storage route/service.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    file_name: str = Field(..., min_length=1, max_length=255)
    file_url: str = Field(..., min_length=1, max_length=500)
    file_type: Literal["pdf", "jpg", "jpeg", "png", "doc", "docx"]
    file_size: int = Field(..., gt=0, le=10 * 1024 * 1024, description="Max 10 MB")

    @field_validator("file_name")
    @classmethod
    def clean_file_name(cls, value: str) -> str:
        value = normalize_required_text(value, "file_name")

        if "/" in value or "\\" in value:
            raise ValueError("file_name cannot contain path separators")

        return value


class VerifyLeaveAttachmentRequest(BaseModel):
    """
    Request schema for HR/Admin verifying leave attachment.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    attachment_index: int = Field(..., ge=0)
    is_verified: bool = True
    comments: Optional[str] = Field(default=None, max_length=500)

    @field_validator("comments")
    @classmethod
    def clean_comments(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class ImportHRMSLeaveRecordRequest(BaseModel):
    """
    Request schema for importing/read-only HRMS leave record.

    Use only in controlled sync/admin process.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    company_id: str = Field(default="default", min_length=2, max_length=100)
    external_hrms_id: str = Field(..., min_length=1, max_length=100)

    employee_id: str = Field(..., min_length=1)
    employee_code: str = Field(..., min_length=1, max_length=50)
    employee_name: str = Field(..., min_length=2, max_length=150)

    leave_type_id: str = Field(..., min_length=1)
    leave_type_code: str = Field(..., min_length=1, max_length=50)
    leave_type_name: str = Field(..., min_length=2, max_length=150)

    start_date: date
    end_date: date
    total_days: float = Field(..., gt=0.0, le=365.0)

    status: LeaveStatus
    reason: str = Field(default="Imported from HRMS", min_length=10, max_length=1000)

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)

    @field_validator("employee_code", "leave_type_code")
    @classmethod
    def normalize_codes(cls, value: str) -> str:
        normalized = normalize_code(value)
        if not normalized:
            raise ValueError("code cannot be empty")
        return normalized

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")

        return self


# -------------------------
# Response Schemas
# -------------------------


class LeaveRequestResponse(BaseModel):
    """
    Normal leave request response.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str

    source: LeaveSource = LeaveSource.LOCAL
    external_hrms_id: Optional[str] = None
    is_read_only: bool = False

    leave_request_id: str
    employee_id: str
    employee_code: str
    employee_name: str

    department_id: Optional[str] = None
    department_name: Optional[str] = None
    manager_id: Optional[str] = None
    manager_name: Optional[str] = None

    leave_type_id: str
    leave_type_code: str
    leave_type_name: str

    start_date: date
    end_date: date
    leave_days: List[LeaveDay] = Field(default_factory=list)
    total_days: float

    reason: str
    contact_during_leave: Optional[str] = None
    handover_notes: Optional[str] = None

    status: LeaveStatus
    approval_chain: List[LeaveApprovalStep] = Field(default_factory=list)
    current_approver_id: Optional[str] = None
    current_approver_name: Optional[str] = None
    requires_hr_approval: bool = False

    attachments: List[LeaveAttachment] = Field(default_factory=list)
    documentation_required: bool = False
    documentation_received: bool = False

    balance_before: float
    balance_reserved: float = 0.0
    balance_after: Optional[float] = None
    balance_action: LeaveBalanceAction = LeaveBalanceAction.NONE

    is_emergency: bool = False
    is_backdated: bool = False
    is_half_day: bool = False
    has_conflict: bool = False
    conflict_leave_request_ids: List[str] = Field(default_factory=list)

    applied_date: datetime
    approved_date: Optional[datetime] = None
    rejected_date: Optional[datetime] = None
    cancelled_date: Optional[datetime] = None
    withdrawn_date: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
    withdrawal_reason: Optional[str] = None

    created_at: datetime
    updated_at: datetime


class LeaveRequestPrivateResponse(LeaveRequestResponse):
    """
    HR/Admin private leave response.
    """

    created_by: str
    updated_by: Optional[str] = None


class LeaveRequestSummaryResponse(BaseModel):
    """
    Lightweight leave request summary.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str

    leave_request_id: str

    employee_id: str
    employee_code: str
    employee_name: str

    department_name: Optional[str] = None
    manager_name: Optional[str] = None

    leave_type_code: str
    leave_type_name: str

    start_date: date
    end_date: date
    total_days: float

    status: LeaveStatus
    current_approver_id: Optional[str] = None

    is_emergency: bool = False
    is_backdated: bool = False
    is_half_day: bool = False
    has_conflict: bool = False

    applied_date: datetime


class LeaveRequestCreatedResponse(BaseModel):
    """
    Response after successful leave creation.
    """

    message: str = Field(default="Leave request created successfully")
    leave_id: str
    leave_request_id: str
    status: LeaveStatus
    leave: Optional[LeaveRequestResponse] = None


class LeaveRequestUpdatedResponse(BaseModel):
    """
    Response after successful leave update.
    """

    message: str = Field(default="Leave request updated successfully")
    leave_request_id: str
    updated_at: datetime
    leave: Optional[LeaveRequestResponse] = None


class LeaveActionResponse(BaseModel):
    """
    Response after leave action.
    """

    message: str
    leave_request_id: str
    status: LeaveStatus
    action_date: datetime
    leave: Optional[LeaveRequestResponse] = None


class LeaveAttachmentResponse(BaseModel):
    """
    Response after attachment action.
    """

    message: str
    leave_request_id: str
    attachments: List[LeaveAttachment] = Field(default_factory=list)


# -------------------------
# Filter and Search Schemas
# -------------------------


class LeaveFilterParams(BaseModel):
    """
    Query parameters for filtering leaves.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    company_id: str = Field(default="default", min_length=2, max_length=100)

    employee_id: Optional[str] = None
    employee_code: Optional[str] = None

    status: Optional[LeaveStatus] = None
    statuses: Optional[List[LeaveStatus]] = None

    leave_type_id: Optional[str] = None
    leave_type_code: Optional[str] = None

    department_id: Optional[str] = None
    manager_id: Optional[str] = None
    current_approver_id: Optional[str] = None

    source: Optional[LeaveSource] = None
    is_read_only: Optional[bool] = None

    start_date_from: Optional[date] = None
    start_date_to: Optional[date] = None

    applied_date_from: Optional[date] = None
    applied_date_to: Optional[date] = None

    is_emergency: Optional[bool] = None
    is_backdated: Optional[bool] = None
    is_half_day: Optional[bool] = None
    has_conflict: Optional[bool] = None

    documentation_required: Optional[bool] = None
    documentation_received: Optional[bool] = None

    search: Optional[str] = Field(default=None, max_length=100)

    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)

    sort_by: Literal[
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
    ] = "applied_date"

    sort_order: Literal["asc", "desc"] = "desc"

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)

    @field_validator(
        "employee_id",
        "employee_code",
        "leave_type_id",
        "leave_type_code",
        "department_id",
        "manager_id",
        "current_approver_id",
        "search",
    )
    @classmethod
    def clean_optional_filters(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_date_ranges(self):
        if self.start_date_from and self.start_date_to:
            if self.start_date_to < self.start_date_from:
                raise ValueError("start_date_to cannot be before start_date_from")

        if self.applied_date_from and self.applied_date_to:
            if self.applied_date_to < self.applied_date_from:
                raise ValueError("applied_date_to cannot be before applied_date_from")

        return self


class LeaveSearchParams(BaseModel):
    """
    Search query parameters.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    company_id: str = Field(default="default", min_length=2, max_length=100)
    query: str = Field(..., min_length=1, max_length=100)

    employee_id: Optional[str] = None
    status: Optional[LeaveStatus] = None
    leave_type_code: Optional[str] = None

    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        return normalize_required_text(value, "query")


class LeaveCalendarParams(BaseModel):
    """
    Calendar query params.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    company_id: str = Field(default="default", min_length=2, max_length=100)
    start_date: date
    end_date: date

    department_id: Optional[str] = None
    manager_id: Optional[str] = None
    include_pending: bool = True

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")

        return self


# -------------------------
# List Responses
# -------------------------


class LeaveRequestListResponse(BaseModel):
    """
    Paginated leave request list response.
    """

    leaves: List[LeaveRequestSummaryResponse]
    total: int
    skip: int
    limit: int


class LeavePendingApprovalsResponse(BaseModel):
    """
    Pending approvals response for managers.
    """

    leaves: List[LeaveRequestSummaryResponse]
    total: int
    skip: int = 0
    limit: int = 100


# -------------------------
# Statistics Responses
# -------------------------


class LeaveStatisticsResponse(BaseModel):
    """
    Leave statistics for employee.
    """

    company_id: str = "default"
    employee_id: str
    year: int

    total_requests: int = 0
    total_days_taken: float = 0.0

    pending: int = 0
    manager_approved: int = 0
    approved: int = 0
    rejected: int = 0
    cancelled: int = 0
    withdrawn: int = 0


class LeaveDashboardStatisticsResponse(BaseModel):
    """
    Leave dashboard statistics for HR/Admin.
    """

    company_id: str = "default"

    total_requests: int = 0
    pending_requests: int = 0
    manager_approved_requests: int = 0
    approved_requests: int = 0
    rejected_requests: int = 0
    cancelled_requests: int = 0
    withdrawn_requests: int = 0

    emergency_requests: int = 0
    backdated_requests: int = 0
    documentation_pending: int = 0


class LeaveTypeStatisticsResponse(BaseModel):
    """
    Leave statistics grouped by leave type.
    """

    leave_type_code: str
    leave_type_name: Optional[str] = None
    request_count: int = 0
    approved_count: int = 0
    approved_days: float = 0.0


class LeaveBalanceResponse(BaseModel):
    """
    Leave balance response.
    """

    employee_id: str
    employee_code: str
    leave_type_code: str
    leave_type_name: str

    granted: float
    used: float
    available: float
    carried_forward: float
    encashed: float

    year: int


class LeaveCalendarDayResponse(BaseModel):
    """
    Single day in leave calendar.
    """

    date: date
    is_weekend: bool
    is_holiday: bool
    holiday_name: Optional[str] = None

    employees_on_leave: List[str] = Field(default_factory=list)
    leave_count: int = 0


class LeaveCalendarResponse(BaseModel):
    """
    Leave calendar response.
    """

    company_id: str
    start_date: date
    end_date: date
    days: List[LeaveCalendarDayResponse] = Field(default_factory=list)
    leaves: List[LeaveRequestSummaryResponse] = Field(default_factory=list)


# -------------------------
# HRMS mode / capability response
# -------------------------


class LeaveModuleCapabilitiesResponse(BaseModel):
    """
    Shows what leave actions are allowed in current deployment mode.
    """

    mode: Literal["local_mvp", "hrms_readonly", "hrms_write_approved"] = "local_mvp"

    can_create_leave: bool = True
    can_update_leave: bool = True
    can_approve_leave: bool = True
    can_cancel_leave: bool = True
    can_read_hrms: bool = False
    stores_leave_locally: bool = True