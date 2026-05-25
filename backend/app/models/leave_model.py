"""
Leave request model - Leave application and approval workflow.

Pattern:
- Employee applies for leave through AI agent or web interface
- System validates against leave balance, holidays, weekends, and business rules
- Leave goes through approval workflow: manager -> HR if required
- Leave balance is deducted/reserved according to service-layer rules
- Leave can be cancelled or withdrawn based on status and policy

Important production note:
- In standalone MVP/local mode, leave requests can be stored in MongoDB.
- In HRMS read-only production mode, this model can be used for:
  - displaying HRMS leave records
  - temporary request drafts if company allows
  - AI-side workflow records if approved by company
- If the company does not allow local storage, write APIs must be disabled and
  leave data should be fetched from HRMS read-only APIs only.

Integration points:
- employee_model.py: leave_balances field tracks available days in MVP/local mode
- leave_type_model.py: leave type rules and validations
- holiday_model.py: exclude holidays from working day calculation
- company_setting_model.py: leave policy rules
- HRMS integration layer: source of truth in production mode
"""

from __future__ import annotations

import re
from datetime import date as Date, datetime as DateTime
from enum import Enum
from typing import List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
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
    Strip required text fields and reject empty values.
    """
    value = str(value).strip()

    if not value:
        raise ValueError(f"{field_name} cannot be empty")

    return value


def normalize_code(value: str, field_name: str) -> str:
    """
    Normalize short codes like employee_code and leave_type_code.
    """
    value = normalize_required_text(value, field_name).upper()

    if not re.fullmatch(r"^[A-Z0-9_-]+$", value):
        raise ValueError(
            f"{field_name} can contain only uppercase letters, numbers, hyphen, and underscore"
        )

    return value


def normalize_company_id(value: Optional[str]) -> str:
    """
    Normalize company_id.

    Rules:
    - default if missing
    - lowercase
    - only letters, numbers, hyphen, underscore
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


# -------------------------
# Enums
# -------------------------


class LeaveStatus(str, Enum):
    """
    Leave request status in approval workflow.
    """

    DRAFT = "draft"
    PENDING = "pending"
    MANAGER_APPROVED = "manager_approved"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    WITHDRAWN = "withdrawn"


class LeaveDayType(str, Enum):
    """
    Type of leave day.
    """

    FULL_DAY = "full_day"
    FIRST_HALF = "first_half"
    SECOND_HALF = "second_half"


class LeaveApprovalStatus(str, Enum):
    """
    Status of a single approval step.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class LeaveApproverRole(str, Enum):
    """
    Role of leave approver.
    """

    MANAGER = "manager"
    HR = "hr"
    ADMIN = "admin"


class LeaveRejectionReason(str, Enum):
    """
    Common rejection reasons.
    """

    INSUFFICIENT_BALANCE = "insufficient_balance"
    TEAM_UNAVAILABLE = "team_unavailable"
    CRITICAL_PERIOD = "critical_period"
    SHORT_NOTICE = "short_notice"
    DOCUMENTATION_MISSING = "documentation_missing"
    POLICY_VIOLATION = "policy_violation"
    DUPLICATE_REQUEST = "duplicate_request"
    CONFLICTING_LEAVE = "conflicting_leave"
    OTHER = "other"


class LeaveSource(str, Enum):
    """
    Where this leave record/request came from.

    LOCAL:
        Created in our MVP/local MongoDB workflow.

    HRMS:
        Read from company HRMS.

    AI_AGENT:
        Created by AI-assisted workflow after user confirmation.

    IMPORTED:
        Imported/synced from external system.
    """

    LOCAL = "local"
    HRMS = "hrms"
    AI_AGENT = "ai_agent"
    IMPORTED = "imported"


class LeaveBalanceAction(str, Enum):
    """
    How leave balance should be handled by service layer.
    """

    NONE = "none"
    RESERVED = "reserved"
    DEDUCTED = "deducted"
    RELEASED = "released"


# -------------------------
# Nested Models
# -------------------------


class LeaveDay(BaseModel):
    """
    Individual leave day details.

    Service layer should calculate:
    - is_holiday
    - is_weekend
    - deduction
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    date: Date = Field(..., description="Leave date")

    day_type: LeaveDayType = Field(
        default=LeaveDayType.FULL_DAY,
        description="Full day or half day",
    )

    is_holiday: bool = Field(
        default=False,
        description="Is this date a company holiday",
    )

    is_weekend: bool = Field(
        default=False,
        description="Is this date a weekend",
    )

    deduction: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Days to deduct from balance",
    )

    holiday_name: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Holiday name if applicable",
    )

    @field_validator("holiday_name")
    @classmethod
    def clean_holiday_name(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_deduction_against_day_type(self):
        """
        Ensure deduction matches day type.
        """
        if self.day_type == LeaveDayType.FULL_DAY and self.deduction not in {0.0, 1.0}:
            raise ValueError("Full day leave deduction must be 0.0 or 1.0")

        if self.day_type in {LeaveDayType.FIRST_HALF, LeaveDayType.SECOND_HALF}:
            if self.deduction not in {0.0, 0.5}:
                raise ValueError("Half-day leave deduction must be 0.0 or 0.5")

        if (self.is_holiday or self.is_weekend) and self.deduction > 0:
            raise ValueError("Holiday/weekend leave day cannot have positive deduction")

        return self


class LeaveApprovalStep(BaseModel):
    """
    Approval step in leave workflow.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    step_order: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Approval step order",
    )

    approver_id: str = Field(..., min_length=1, description="Employee ID of approver")

    approver_name: str = Field(
        ...,
        min_length=2,
        max_length=150,
        description="Name of approver",
    )

    approver_role: LeaveApproverRole = Field(
        ...,
        description="Approver role",
    )

    status: LeaveApprovalStatus = Field(
        default=LeaveApprovalStatus.PENDING,
        description="Approval step status",
    )

    comments: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Approval/rejection comments",
    )

    rejection_reason: Optional[LeaveRejectionReason] = Field(
        default=None,
        description="Reason for rejection",
    )

    action_date: Optional[DateTime] = Field(
        default=None,
        description="When action was taken",
    )

    delegated_to_id: Optional[str] = Field(
        default=None,
        description="Delegated approver employee ID",
    )

    delegated_to_name: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Delegated approver name",
    )

    @field_validator("approver_id", "delegated_to_id")
    @classmethod
    def clean_optional_ids(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("approver_name", "delegated_to_name")
    @classmethod
    def clean_names(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("comments")
    @classmethod
    def clean_comments(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_approval_step(self):
        """
        Validate action fields based on status.
        """
        if self.status in {
            LeaveApprovalStatus.APPROVED,
            LeaveApprovalStatus.REJECTED,
            LeaveApprovalStatus.SKIPPED,
        }:
            if self.action_date is None:
                raise ValueError("action_date is required when approval step is completed")

        if self.status == LeaveApprovalStatus.REJECTED and self.rejection_reason is None:
            raise ValueError("rejection_reason is required when approval step is rejected")

        if self.status != LeaveApprovalStatus.REJECTED and self.rejection_reason is not None:
            raise ValueError("rejection_reason can be set only for rejected approval step")

        return self


class LeaveAttachment(BaseModel):
    """
    Leave supporting document.

    File upload/storage should be handled by service/storage layer.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    file_name: str = Field(..., min_length=1, max_length=255)
    file_url: str = Field(..., min_length=1, max_length=500)
    file_type: str = Field(..., min_length=1, max_length=50)
    file_size: int = Field(..., gt=0, le=10 * 1024 * 1024, description="Max 10 MB")

    uploaded_by: str = Field(..., min_length=1, description="Employee ID of uploader")
    uploaded_at: DateTime = Field(default_factory=DateTime.utcnow)

    is_verified: bool = Field(
        default=False,
        description="Whether HR verified the document",
    )

    verified_by: Optional[str] = Field(
        default=None,
        description="Employee ID of verifier",
    )

    verified_at: Optional[DateTime] = None

    @field_validator("file_name")
    @classmethod
    def clean_file_name(cls, value: str) -> str:
        value = normalize_required_text(value, "file_name")

        if "/" in value or "\\" in value:
            raise ValueError("file_name cannot contain path separators")

        return value

    @field_validator("file_type")
    @classmethod
    def clean_file_type(cls, value: str) -> str:
        value = normalize_required_text(value, "file_type").lower()

        allowed = {
            "pdf",
            "jpg",
            "jpeg",
            "png",
            "doc",
            "docx",
        }

        if value not in allowed:
            raise ValueError(
                "file_type must be one of: pdf, jpg, jpeg, png, doc, docx"
            )

        return value

    @field_validator("uploaded_by", "verified_by")
    @classmethod
    def clean_ids(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_verification_fields(self):
        if self.is_verified:
            if not self.verified_by or self.verified_at is None:
                raise ValueError("verified_by and verified_at are required when is_verified=True")

        return self


class LeavePolicySnapshot(BaseModel):
    """
    Snapshot of important leave policy values used during request creation.

    This protects historical requests if policy changes later.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    leave_type_code: str
    requires_approval: bool = True
    requires_documentation: bool = False
    available_during_probation: bool = True
    max_consecutive_days: Optional[int] = None
    min_notice_days: Optional[int] = None
    allow_half_day: bool = True
    allow_backdated: bool = False

    @field_validator("leave_type_code")
    @classmethod
    def clean_leave_type_code(cls, value: str) -> str:
        return normalize_code(value, "leave_type_code")


# -------------------------
# Main Leave Request Model
# -------------------------


class LeaveRequest(BaseModel):
    """
    Leave request document model for leave_requests collection.

    Represents employee leave applications with approval workflow.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    # -------------------------
    # Multi-company / source support
    # -------------------------

    company_id: str = Field(
        default="default",
        min_length=2,
        max_length=100,
        description="Company identifier",
    )

    source: LeaveSource = Field(
        default=LeaveSource.LOCAL,
        description="Where this record came from",
    )

    external_hrms_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="External HRMS leave request ID if record comes from HRMS",
    )

    is_read_only: bool = Field(
        default=False,
        description="True if this record is read from HRMS and cannot be modified locally",
    )

    # -------------------------
    # Core Identity
    # -------------------------

    leave_request_id: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Unique leave request ID, e.g. LV-2026-0001",
    )

    employee_id: str = Field(
        ...,
        min_length=1,
        description="Reference to employees._id or HRMS employee ID",
    )

    employee_code: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Employee code for quick reference",
    )

    employee_name: str = Field(
        ...,
        min_length=2,
        max_length=150,
        description="Employee full name",
    )

    department_id: Optional[str] = Field(
        default=None,
        description="Department id at request time",
    )

    department_name: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Department name at request time",
    )

    manager_id: Optional[str] = Field(
        default=None,
        description="Manager employee id at request time",
    )

    manager_name: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Manager name at request time",
    )

    # -------------------------
    # Leave Type and Duration
    # -------------------------

    leave_type_id: str = Field(
        ...,
        min_length=1,
        description="Reference to leave_types._id or HRMS leave type ID",
    )

    leave_type_code: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Leave type code",
    )

    leave_type_name: str = Field(
        ...,
        min_length=2,
        max_length=150,
        description="Leave type name for display",
    )

    start_date: Date = Field(..., description="Leave start date inclusive")
    end_date: Date = Field(..., description="Leave end date inclusive")

    leave_days: List[LeaveDay] = Field(
        default_factory=list,
        description="Detailed breakdown of each leave day",
    )

    total_days: float = Field(
        ...,
        gt=0.0,
        le=365.0,
        description="Total leave days to be deducted",
    )

    # -------------------------
    # Leave Details
    # -------------------------

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

    # -------------------------
    # Approval Workflow
    # -------------------------

    status: LeaveStatus = Field(
        default=LeaveStatus.PENDING,
        description="Current leave status",
    )

    approval_chain: List[LeaveApprovalStep] = Field(
        default_factory=list,
        description="Approval workflow steps",
    )

    current_approver_id: Optional[str] = Field(
        default=None,
        description="Employee ID of current pending approver",
    )

    requires_hr_approval: bool = Field(
        default=False,
        description="Does this leave need HR approval after manager",
    )

    # -------------------------
    # Supporting Documents
    # -------------------------

    attachments: List[LeaveAttachment] = Field(
        default_factory=list,
        description="Medical certificates or supporting documents",
    )

    documentation_required: bool = Field(
        default=False,
        description="Is documentation required for this leave",
    )

    documentation_received: bool = Field(
        default=False,
        description="Whether required documentation has been uploaded",
    )

    # -------------------------
    # Balance Tracking
    # -------------------------

    balance_before: float = Field(
        ...,
        ge=0.0,
        description="Leave balance before this request",
    )

    balance_reserved: float = Field(
        default=0.0,
        ge=0.0,
        description="Balance reserved on submission if service uses reservation",
    )

    balance_after: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Leave balance after approval",
    )

    balance_action: LeaveBalanceAction = Field(
        default=LeaveBalanceAction.NONE,
        description="Current balance handling state",
    )

    # -------------------------
    # Policy snapshot
    # -------------------------

    policy_snapshot: Optional[LeavePolicySnapshot] = Field(
        default=None,
        description="Leave policy values at request creation time",
    )

    # -------------------------
    # Special Flags
    # -------------------------

    is_emergency: bool = Field(
        default=False,
        description="Emergency leave with reduced notice period",
    )

    is_backdated: bool = Field(
        default=False,
        description="Leave applied after start date",
    )

    is_half_day: bool = Field(
        default=False,
        description="Is any day a half-day leave",
    )

    has_conflict: bool = Field(
        default=False,
        description="Whether this leave conflicts with another approved/pending leave",
    )

    conflict_leave_request_ids: List[str] = Field(
        default_factory=list,
        description="Conflicting leave request IDs",
    )

    # -------------------------
    # Metadata
    # -------------------------

    applied_date: DateTime = Field(
        default_factory=DateTime.utcnow,
        description="When leave was applied",
    )

    approved_date: Optional[DateTime] = Field(
        default=None,
        description="When leave was fully approved",
    )

    rejected_date: Optional[DateTime] = Field(
        default=None,
        description="When leave was rejected",
    )

    cancelled_date: Optional[DateTime] = Field(
        default=None,
        description="When leave was cancelled",
    )

    withdrawn_date: Optional[DateTime] = Field(
        default=None,
        description="When approved leave was withdrawn",
    )

    cancellation_reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Reason for cancellation",
    )

    withdrawal_reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Reason for withdrawal",
    )

    created_by: str = Field(
        ...,
        min_length=1,
        description="Employee/User ID who created this request",
    )

    updated_by: Optional[str] = Field(
        default=None,
        description="Employee/User ID who last updated",
    )

    created_at: DateTime = Field(
        default_factory=DateTime.utcnow,
        description="Creation timestamp",
    )

    updated_at: DateTime = Field(
        default_factory=DateTime.utcnow,
        description="Last update timestamp",
    )

    # -------------------------
    # Validators
    # -------------------------

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)

    @field_validator("leave_request_id")
    @classmethod
    def validate_leave_request_id(cls, value: str) -> str:
        value = normalize_required_text(value, "leave_request_id").upper()

        if not re.fullmatch(r"^[A-Z0-9_-]+$", value):
            raise ValueError(
                "leave_request_id can contain only uppercase letters, numbers, hyphen, and underscore"
            )

        return value

    @field_validator("employee_code", "leave_type_code")
    @classmethod
    def normalize_codes(cls, value: str) -> str:
        return normalize_code(value, "code")

    @field_validator("employee_name", "leave_type_name")
    @classmethod
    def clean_required_names(cls, value: str) -> str:
        return normalize_required_text(value, "name")

    @field_validator(
        "external_hrms_id",
        "department_id",
        "department_name",
        "manager_id",
        "manager_name",
        "contact_during_leave",
        "handover_notes",
        "current_approver_id",
        "cancellation_reason",
        "withdrawal_reason",
        "updated_by",
    )
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
    def validate_leave_dates(self):
        """
        Validate leave date logic.
        """
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")

        if self.leave_days:
            leave_day_dates = [leave_day.date for leave_day in self.leave_days]

            if min(leave_day_dates) < self.start_date:
                raise ValueError("leave_days cannot contain date before start_date")

            if max(leave_day_dates) > self.end_date:
                raise ValueError("leave_days cannot contain date after end_date")

            if len(leave_day_dates) != len(set(leave_day_dates)):
                raise ValueError("leave_days cannot contain duplicate dates")

            calculated_total = sum(day.deduction for day in self.leave_days)

            if abs(calculated_total - self.total_days) > 0.01:
                raise ValueError(
                    f"leave_days total ({calculated_total}) does not match total_days ({self.total_days})"
                )

            has_half_day = any(
                day.day_type in {LeaveDayType.FIRST_HALF, LeaveDayType.SECOND_HALF}
                for day in self.leave_days
            )

            if self.is_half_day != has_half_day:
                raise ValueError("is_half_day must match leave_days half-day values")

        return self

    @model_validator(mode="after")
    def validate_balance(self):
        """
        Validate leave balance logic.
        """
        if self.balance_reserved > self.balance_before:
            raise ValueError("balance_reserved cannot be greater than balance_before")

        if self.balance_reserved > self.total_days:
            raise ValueError("balance_reserved cannot be greater than total_days")

        if self.balance_after is not None:
            if self.balance_after > self.balance_before:
                raise ValueError("balance_after cannot be greater than balance_before")

        if self.balance_action == LeaveBalanceAction.RESERVED:
            if self.balance_reserved <= 0:
                raise ValueError("balance_reserved must be greater than 0 when balance_action=reserved")

        if self.balance_action == LeaveBalanceAction.DEDUCTED:
            if self.balance_after is None:
                raise ValueError("balance_after is required when balance_action=deducted")

        return self

    @model_validator(mode="after")
    def validate_documentation(self):
        """
        Validate documentation fields.
        """
        if self.documentation_required:
            if self.status == LeaveStatus.APPROVED and not self.documentation_received:
                raise ValueError("documentation_received must be true before approval")

        if self.attachments and not self.documentation_received:
            raise ValueError("documentation_received must be true when attachments exist")

        return self

    @model_validator(mode="after")
    def validate_status_dates(self):
        """
        Validate lifecycle timestamps.
        """
        if self.status == LeaveStatus.APPROVED and self.approved_date is None:
            raise ValueError("approved_date is required when status=approved")

        if self.status == LeaveStatus.REJECTED and self.rejected_date is None:
            raise ValueError("rejected_date is required when status=rejected")

        if self.status == LeaveStatus.CANCELLED:
            if self.cancelled_date is None:
                raise ValueError("cancelled_date is required when status=cancelled")
            if not self.cancellation_reason:
                raise ValueError("cancellation_reason is required when status=cancelled")

        if self.status == LeaveStatus.WITHDRAWN:
            if self.withdrawn_date is None:
                raise ValueError("withdrawn_date is required when status=withdrawn")
            if not self.withdrawal_reason:
                raise ValueError("withdrawal_reason is required when status=withdrawn")

        if self.status in {
            LeaveStatus.DRAFT,
            LeaveStatus.PENDING,
            LeaveStatus.MANAGER_APPROVED,
        }:
            if self.approved_date or self.rejected_date or self.cancelled_date or self.withdrawn_date:
                raise ValueError(
                    "final lifecycle dates cannot be set for draft/pending/manager_approved status"
                )

        return self

    @model_validator(mode="after")
    def validate_approval_workflow(self):
        """
        Validate approval workflow consistency.
        """
        pending_steps = [
            step for step in self.approval_chain
            if step.status == LeaveApprovalStatus.PENDING
        ]

        if self.status in {LeaveStatus.PENDING, LeaveStatus.MANAGER_APPROVED}:
            if self.approval_chain and not pending_steps:
                raise ValueError("pending leave status requires at least one pending approval step")

            if self.current_approver_id is None and pending_steps:
                raise ValueError("current_approver_id is required when approval step is pending")

        if self.status in {
            LeaveStatus.APPROVED,
            LeaveStatus.REJECTED,
            LeaveStatus.CANCELLED,
            LeaveStatus.WITHDRAWN,
        }:
            if self.current_approver_id is not None:
                raise ValueError("current_approver_id must be None for final statuses")

        return self

    @model_validator(mode="after")
    def validate_source_rules(self):
        """
        Validate HRMS/read-only rules.
        """
        if self.source == LeaveSource.HRMS:
            if not self.external_hrms_id:
                raise ValueError("external_hrms_id is required when source=hrms")
            if not self.is_read_only:
                raise ValueError("HRMS-sourced leave records must be read-only")

        return self


class LeaveRequestInDB(LeaveRequest):
    """
    Leave request model as stored in MongoDB with _id field.
    """

    id: Optional[str] = Field(default=None, alias="_id")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )


# -------------------------
# Response Models
# -------------------------


class LeaveRequestResponse(BaseModel):
    """
    Safe leave request response for API output.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    source: LeaveSource
    external_hrms_id: Optional[str] = None
    is_read_only: bool

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

    start_date: Date
    end_date: Date
    leave_days: List[LeaveDay]
    total_days: float

    reason: str
    contact_during_leave: Optional[str] = None
    handover_notes: Optional[str] = None

    status: LeaveStatus
    approval_chain: List[LeaveApprovalStep]
    current_approver_id: Optional[str] = None
    requires_hr_approval: bool

    attachments: List[LeaveAttachment] = Field(default_factory=list)
    documentation_required: bool
    documentation_received: bool

    balance_before: float
    balance_reserved: float
    balance_after: Optional[float] = None
    balance_action: LeaveBalanceAction

    policy_snapshot: Optional[LeavePolicySnapshot] = None

    is_emergency: bool
    is_backdated: bool
    is_half_day: bool
    has_conflict: bool
    conflict_leave_request_ids: List[str] = Field(default_factory=list)

    applied_date: DateTime
    approved_date: Optional[DateTime] = None
    rejected_date: Optional[DateTime] = None
    cancelled_date: Optional[DateTime] = None
    withdrawn_date: Optional[DateTime] = None
    cancellation_reason: Optional[str] = None
    withdrawal_reason: Optional[str] = None

    created_at: DateTime
    updated_at: DateTime


class LeaveRequestPrivateResponse(LeaveRequestResponse):
    """
    Private response for HR/Admin if later needed.

    Currently same as normal response, but kept separate so we can add internal
    audit fields safely without changing normal employee response.
    """

    created_by: str
    updated_by: Optional[str] = None


class LeaveRequestSummary(BaseModel):
    """
    Lightweight leave request summary for list pages.
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

    start_date: Date
    end_date: Date
    total_days: float

    status: LeaveStatus
    current_approver_id: Optional[str] = None

    is_emergency: bool
    is_backdated: bool
    is_half_day: bool
    has_conflict: bool

    applied_date: DateTime


class LeaveSummaryByEmployee(BaseModel):
    """
    Leave summary for employee dashboard.
    """

    model_config = ConfigDict(from_attributes=True)

    employee_id: str
    employee_code: str
    employee_name: str

    total_leaves_taken: float = 0.0
    pending_leaves: int = 0
    approved_leaves: int = 0
    rejected_leaves: int = 0
    cancelled_leaves: int = 0
    withdrawn_leaves: int = 0

    upcoming_leaves: List[LeaveRequestSummary] = Field(default_factory=list)


class LeaveDashboardStatistics(BaseModel):
    """
    Leave statistics for HR/Admin dashboard.
    """

    model_config = ConfigDict(from_attributes=True)

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