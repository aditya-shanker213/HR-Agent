"""
Claim/Reimbursement model for the claims collection.

Represents employee expense claims/reimbursements like travel, food, medical,
internet, relocation, office expenses, etc.

Production-style design:
- MongoDB is mock HRMS for MVP.
- In production, external HRMS can become source of truth.
- HRMS/imported read-only records are supported.
- Business rules that depend on DB/company settings must stay in service layer.
- This model validates document shape, safe field values, lifecycle consistency,
  and snapshot structures.

Important:
- claim_type_id references claim_types collection.
- employee_id references employees collection.
- company_id supports future multi-company / multi-tenant use.
- policy_snapshot stores claim policy and claim type rules at creation time.
- approval_steps stores structured approval workflow.
- action_history stores audit-style events.
"""

from __future__ import annotations

import re
from datetime import date as Date
from datetime import datetime as DateTime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# -------------------------
# Constants
# -------------------------

MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

ALLOWED_ATTACHMENT_EXTENSIONS = {
    "pdf",
    "jpg",
    "jpeg",
    "png",
    "doc",
    "docx",
}

CLAIM_ID_PATTERN = re.compile(r"^CLM-\d{4}-\d{4,}$")


# -------------------------
# Shared helpers
# -------------------------


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    """
    Strip optional string fields.

    Empty string becomes None.
    """
    if value is None:
        return None

    value = str(value).strip()
    return value or None


def normalize_required_text(value: str, field_name: str = "value") -> str:
    """
    Strip required string fields.
    """
    value = str(value).strip()

    if not value:
        raise ValueError(f"{field_name} cannot be empty")

    return value


def normalize_company_id(value: Optional[str]) -> str:
    """
    Normalize company_id.

    Rules:
    - default if missing
    - lowercase
    - only letters, numbers, underscore, hyphen
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


def normalize_currency(value: Optional[str]) -> str:
    """
    Normalize currency code.

    Company-specific allowed currency should be checked in service layer using
    company settings / claim policy.
    """
    if value is None:
        return "INR"

    value = str(value).strip().upper()

    if not value:
        return "INR"

    if not value.isalpha() or len(value) != 3:
        raise ValueError("currency must be a valid 3-letter code, for example INR")

    return value


def normalize_file_extension(value: str) -> str:
    """
    Normalize file extension or MIME-ish file type value.

    Accepts:
    - pdf
    - .pdf
    - application/pdf
    - image/jpeg
    """
    value = str(value).strip().lower()

    if not value:
        raise ValueError("file_type cannot be empty")

    if "/" in value:
        value = value.split("/")[-1]

    value = value.replace(".", "").strip()

    # Normalize common MIME suffix.
    if value == "vnd.openxmlformats-officedocument.wordprocessingml.document":
        value = "docx"
    elif value == "msword":
        value = "doc"

    if value not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValueError(
            "file_type must be one of: "
            f"{', '.join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))}"
        )

    return value


# -------------------------
# Enums
# -------------------------


class ClaimSource(str, Enum):
    """
    Source of claim record.

    local:
        Created inside this MVP/backend.
    hrms:
        Imported/read from external HRMS.
    ai_agent:
        Created by AI workflow after user confirmation.
    imported:
        Imported from file/batch/sync.
    """

    LOCAL = "local"
    HRMS = "hrms"
    AI_AGENT = "ai_agent"
    IMPORTED = "imported"


class ClaimStatus(str, Enum):
    """
    Claim lifecycle status.
    """

    DRAFT = "draft"
    PENDING = "pending"
    MANAGER_APPROVED = "manager_approved"
    FINANCE_APPROVED = "finance_approved"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    WITHDRAWN = "withdrawn"
    SENT_BACK = "sent_back"
    RESUBMITTED = "resubmitted"
    PROCESSING = "processing"
    PAID = "paid"
    FAILED = "failed"


class ClaimPriority(str, Enum):
    """
    Claim urgency level.
    """

    NORMAL = "normal"
    URGENT = "urgent"
    EMERGENCY = "emergency"


class ClaimApproverRole(str, Enum):
    """
    Role expected to act on a claim approval step.
    """

    MANAGER = "manager"
    FINANCE = "finance"
    HR = "hr"
    ADMIN = "admin"


class ClaimApprovalStatus(str, Enum):
    """
    Status of one approval step.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"
    SENT_BACK = "sent_back"


class ClaimActionType(str, Enum):
    """
    Audit/action history event type.
    """

    CREATED = "created"
    SUBMITTED = "submitted"
    RESUBMITTED = "resubmitted"
    MANAGER_APPROVED = "manager_approved"
    FINANCE_APPROVED = "finance_approved"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT_BACK = "sent_back"
    CANCELLED = "cancelled"
    WITHDRAWN = "withdrawn"
    PROCESSING_STARTED = "processing_started"
    PAID = "paid"
    PAYMENT_FAILED = "payment_failed"
    UPDATED = "updated"
    SYNCED_TO_HRMS = "synced_to_hrms"
    IMPORTED_FROM_HRMS = "imported_from_hrms"


class ClaimPaymentStatus(str, Enum):
    """
    Payment processing status.
    """

    NOT_STARTED = "not_started"
    QUEUED = "queued"
    PROCESSING = "processing"
    PAID = "paid"
    FAILED = "failed"
    ON_HOLD = "on_hold"


# -------------------------
# Nested models
# -------------------------


class ClaimPolicySnapshot(BaseModel):
    """
    Claim policy snapshot captured when claim is created.

    This stores the effective company policy + claim type rules at creation time.
    Actual validation against current DB/company settings should happen in
    claim_service.py before creating or updating a claim.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    requires_bill: bool = Field(
        default=False,
        description="Whether this claim type requires bill attachment",
    )

    require_bill_above: Optional[float] = Field(
        default=None,
        ge=0,
        description="Company-level amount above which bill is mandatory",
    )

    requires_approval: bool = Field(
        default=True,
        description="Whether approval is required",
    )

    auto_approve_below: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "Legacy/reference threshold only. "
            "Service must not use this field to auto-approve claims. "
            "Money-related claims must go through manager/finance/HR approval."
        ),
    )

    manager_approval_threshold: Optional[float] = Field(
        default=None,
        ge=0,
        description="Amount above which manager approval is required",
    )

    finance_approval_threshold: Optional[float] = Field(
        default=None,
        ge=0,
        description="Amount above which finance approval is required",
    )

    max_claim_amount: Optional[float] = Field(
        default=None,
        ge=0,
        description="Maximum amount allowed for one claim",
    )

    monthly_limit: Optional[float] = Field(
        default=None,
        ge=0,
        description="Monthly claim limit snapshot",
    )

    yearly_limit: Optional[float] = Field(
        default=None,
        ge=0,
        description="Yearly claim limit snapshot",
    )

    allowed_file_types: List[str] = Field(
        default_factory=lambda: ["pdf", "jpg", "jpeg", "png", "doc", "docx"],
        description="Allowed bill file extensions",
    )

    allowed_currency: str = Field(
        default="INR",
        min_length=3,
        max_length=3,
        description="Allowed currency at claim creation time",
    )

    claim_submission_deadline_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=365,
        description="Allowed days after expense date to submit claim",
    )

    reimbursement_processing_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=90,
        description="Expected reimbursement processing days",
    )

    captured_at: DateTime = Field(
        default_factory=DateTime.utcnow,
        description="When this policy snapshot was captured",
    )

    @field_validator("allowed_currency")
    @classmethod
    def validate_allowed_currency(cls, value: str) -> str:
        return normalize_currency(value)

    @field_validator("allowed_file_types")
    @classmethod
    def validate_allowed_file_types(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("allowed_file_types cannot be empty")

        cleaned: List[str] = []

        for item in value:
            extension = normalize_file_extension(item)

            if extension not in cleaned:
                cleaned.append(extension)

        return cleaned

    @model_validator(mode="after")
    def validate_threshold_order(self):
        """
        Validate only human approval threshold consistency.

        auto_approve_below is legacy/reference only and must not control approval.
        Full policy logic stays in claim_service.py.
        """
        if (
            self.manager_approval_threshold is not None
            and self.finance_approval_threshold is not None
            and self.finance_approval_threshold < self.manager_approval_threshold
        ):
            raise ValueError(
                "finance_approval_threshold cannot be less than manager_approval_threshold"
            )

        return self


class ClaimAttachment(BaseModel):
    """
    Claim bill/receipt attachment metadata.

    Actual file should be stored outside MongoDB. MongoDB stores only metadata
    and file URL/key/path.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    file_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Original uploaded file name",
    )

    file_url: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Storage URL, local path, S3 key, or blob key",
    )

    file_type: str = Field(
        ...,
        description="File extension or MIME type",
    )

    file_size: int = Field(
        ...,
        gt=0,
        le=MAX_ATTACHMENT_SIZE_BYTES,
        description="File size in bytes, max 10 MB",
    )

    uploaded_by: Optional[str] = Field(
        default=None,
        description="User/employee ID who uploaded file",
    )

    uploaded_at: DateTime = Field(
        default_factory=DateTime.utcnow,
        description="Upload timestamp",
    )

    is_verified: bool = Field(
        default=False,
        description="Whether HR/finance verified this attachment",
    )

    verified_by: Optional[str] = Field(
        default=None,
        description="User ID who verified attachment",
    )

    verified_at: Optional[DateTime] = Field(
        default=None,
        description="Attachment verification timestamp",
    )

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        value = normalize_required_text(value, "file_name")

        if "/" in value or "\\" in value:
            raise ValueError("file_name must not contain path separators")

        if value in {".", ".."}:
            raise ValueError("file_name is invalid")

        if "." not in value:
            raise ValueError("file_name must include a valid extension")

        extension = value.rsplit(".", 1)[-1].lower().strip()

        if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
            raise ValueError(
                "file extension must be one of: "
                f"{', '.join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))}"
            )

        return value

    @field_validator("file_url")
    @classmethod
    def validate_file_url(cls, value: str) -> str:
        return normalize_required_text(value, "file_url")

    @field_validator("file_type")
    @classmethod
    def validate_file_type(cls, value: str) -> str:
        return normalize_file_extension(value)

    @field_validator("uploaded_by", "verified_by")
    @classmethod
    def clean_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_verification_fields(self):
        if self.is_verified:
            if not self.verified_by:
                raise ValueError("verified_by is required when is_verified=True")

            if self.verified_at is None:
                raise ValueError("verified_at is required when is_verified=True")

        if not self.is_verified:
            if self.verified_by is not None or self.verified_at is not None:
                raise ValueError(
                    "verified_by and verified_at must be empty when is_verified=False"
                )

        return self


class ClaimApprovalStep(BaseModel):
    """
    Structured approval workflow step.

    This is separate from action_history. Approval steps represent the planned
    workflow, while action_history stores all audit events.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    step_order: int = Field(
        ...,
        ge=1,
        description="Approval step sequence number",
    )

    approver_role: ClaimApproverRole = Field(
        ...,
        description="Role responsible for this approval step",
    )

    approver_id: Optional[str] = Field(
        default=None,
        description="Specific approver employee/user ID",
    )

    approver_name: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Approver name snapshot",
    )

    approval_status: ClaimApprovalStatus = Field(
        default=ClaimApprovalStatus.PENDING,
        description="Current status of this approval step",
    )

    action_date: Optional[DateTime] = Field(
        default=None,
        description="When approver acted",
    )

    comments: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Approval comments",
    )

    rejection_reason: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Rejection reason if rejected",
    )

    sent_back_reason: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Reason if sent back for correction",
    )

    @field_validator(
        "approver_id",
        "approver_name",
        "comments",
        "rejection_reason",
        "sent_back_reason",
    )
    @classmethod
    def clean_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_step_status_fields(self):
        if self.approval_status in {
            ClaimApprovalStatus.APPROVED,
            ClaimApprovalStatus.REJECTED,
            ClaimApprovalStatus.SKIPPED,
            ClaimApprovalStatus.SENT_BACK,
        }:
            if self.action_date is None:
                raise ValueError(
                    "action_date is required when approval step is acted on"
                )

        if self.approval_status == ClaimApprovalStatus.REJECTED:
            if not self.rejection_reason:
                raise ValueError(
                    "rejection_reason is required when approval_status is rejected"
                )

        if self.approval_status == ClaimApprovalStatus.SENT_BACK:
            if not self.sent_back_reason:
                raise ValueError(
                    "sent_back_reason is required when approval_status is sent_back"
                )

        return self


class ClaimActionHistory(BaseModel):
    """
    Audit-style action history event.

    This does not replace approval_steps.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    action: ClaimActionType = Field(
        ...,
        description="Action performed",
    )

    actor_id: Optional[str] = Field(
        default=None,
        description="User/employee ID who performed action",
    )

    actor_name: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Actor name snapshot",
    )

    actor_role: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Actor role snapshot",
    )

    old_status: Optional[ClaimStatus] = Field(
        default=None,
        description="Previous claim status",
    )

    new_status: Optional[ClaimStatus] = Field(
        default=None,
        description="New claim status",
    )

    comments: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Action comments",
    )

    amount: Optional[float] = Field(
        default=None,
        ge=0,
        description="Amount involved in this action, if applicable",
    )

    action_at: DateTime = Field(
        default_factory=DateTime.utcnow,
        description="Action timestamp",
    )

    extra_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional action-specific data",
    )

    @field_validator("actor_id", "actor_name", "actor_role", "comments")
    @classmethod
    def clean_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


# -------------------------
# Main claim document model
# -------------------------


class Claim(BaseModel):
    """
    Claim document model for claims collection.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=False,
    )

    # Identity
    claim_id: str = Field(
        ...,
        min_length=13,
        max_length=50,
        description="Unique claim identifier, format CLM-YYYY-0001",
    )

    company_id: str = Field(
        default="default",
        min_length=1,
        max_length=100,
        description="Company identifier",
    )

    # HRMS compatibility
    source: ClaimSource = Field(
        default=ClaimSource.LOCAL,
        description="Source of claim record",
    )

    external_hrms_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="External HRMS claim ID if source is HRMS/imported",
    )

    is_read_only: bool = Field(
        default=False,
        description="True for HRMS-owned read-only records",
    )

    # Employee snapshot
    employee_id: str = Field(
        ...,
        min_length=1,
        description="Employee document ID",
    )

    employee_code: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Employee code snapshot",
    )

    employee_name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Employee name snapshot",
    )

    department_id: Optional[str] = Field(
        default=None,
        description="Department ID snapshot",
    )

    department_name: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Department name snapshot",
    )

    manager_id: Optional[str] = Field(
        default=None,
        description="Manager employee ID snapshot",
    )

    manager_name: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Manager name snapshot",
    )

    # Claim type snapshot
    claim_type_id: str = Field(
        ...,
        min_length=1,
        description="Claim type document ID",
    )

    claim_type_code: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Claim type code snapshot",
    )

    claim_type_name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Claim type name snapshot",
    )

    policy_snapshot: ClaimPolicySnapshot = Field(
        default_factory=ClaimPolicySnapshot,
        description="Policy and claim type rule snapshot at claim creation time",
    )

    # Claim details
    title: str = Field(
        ...,
        min_length=5,
        max_length=200,
        description="Short claim title",
    )

    description: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Detailed claim description / justification",
    )

    amount: float = Field(
        ...,
        gt=0,
        description="Requested claim amount",
    )

    currency: str = Field(
        default="INR",
        min_length=3,
        max_length=3,
        description="Currency code",
    )

    expense_date: Date = Field(
        ...,
        description="Date when expense was incurred",
    )

    vendor_name: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Vendor or merchant name",
    )

    bill_number: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Bill/invoice/receipt number",
    )

    project_code: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Internal project/client code",
    )

    cost_center: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Finance cost center",
    )

    # Attachments
    attachments: List[ClaimAttachment] = Field(
        default_factory=list,
        description="Bill/receipt attachment metadata",
    )

    # Lifecycle
    status: ClaimStatus = Field(
        default=ClaimStatus.PENDING,
        description="Current claim status",
    )

    priority: ClaimPriority = Field(
        default=ClaimPriority.NORMAL,
        description="Claim urgency",
    )

    submitted_at: Optional[DateTime] = Field(
        default=None,
        description="Claim submission timestamp",
    )

    resubmitted_at: Optional[DateTime] = Field(
        default=None,
        description="Claim resubmission timestamp",
    )

    sent_back_at: Optional[DateTime] = Field(
        default=None,
        description="When claim was sent back",
    )

    sent_back_reason: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Reason for sending claim back",
    )

    # Approval workflow
    approval_steps: List[ClaimApprovalStep] = Field(
        default_factory=list,
        description="Structured approval workflow steps",
    )

    action_history: List[ClaimActionHistory] = Field(
        default_factory=list,
        description="Audit-style claim action history",
    )

    requires_approval: bool = Field(
        default=True,
        description="Whether claim requires approval",
    )

    current_approval_role: Optional[ClaimApproverRole] = Field(
        default=None,
        description="Current role expected to act",
    )

    approved_amount: Optional[float] = Field(
        default=None,
        ge=0,
        description="Final approved amount",
    )

    approved_at: Optional[DateTime] = Field(
        default=None,
        description="Final approval timestamp",
    )

    approved_by: Optional[str] = Field(
        default=None,
        description="Final approver user/employee ID",
    )

    rejected_at: Optional[DateTime] = Field(
        default=None,
        description="Rejection timestamp",
    )

    rejected_by: Optional[str] = Field(
        default=None,
        description="Rejector user/employee ID",
    )

    rejection_reason: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Final rejection reason",
    )

    # Cancellation / withdrawal
    cancelled_at: Optional[DateTime] = Field(
        default=None,
        description="Cancellation timestamp",
    )

    cancelled_by: Optional[str] = Field(
        default=None,
        description="User/employee ID who cancelled claim",
    )

    cancellation_reason: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Cancellation reason",
    )

    withdrawn_at: Optional[DateTime] = Field(
        default=None,
        description="Withdrawal timestamp",
    )

    withdrawn_by: Optional[str] = Field(
        default=None,
        description="User/employee ID who withdrew claim",
    )

    withdrawal_reason: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Withdrawal reason",
    )

    # Payment fields
    payment_status: ClaimPaymentStatus = Field(
        default=ClaimPaymentStatus.NOT_STARTED,
        description="Payment status",
    )

    payment_reference: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Payment transaction reference",
    )

    payment_date: Optional[Date] = Field(
        default=None,
        description="Payment date",
    )

    payment_failure_reason: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Payment failure reason",
    )

    paid_amount: Optional[float] = Field(
        default=None,
        ge=0,
        description="Actually paid amount",
    )

    # HRMS sync metadata
    synced_to_hrms: bool = Field(
        default=False,
        description="Whether claim has been synced to HRMS",
    )

    synced_at: Optional[DateTime] = Field(
        default=None,
        description="Last HRMS sync timestamp",
    )

    sync_error: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Last HRMS sync error",
    )

    # Notes and flexible data
    employee_notes: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Employee-visible notes",
    )

    internal_notes: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Internal HR/finance notes",
    )

    tags: List[str] = Field(
        default_factory=list,
        description="Search/filter tags",
    )

    extra_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional flexible metadata",
    )

    # Audit fields
    created_by: Optional[str] = Field(
        default=None,
        description="User ID who created claim",
    )

    updated_by: Optional[str] = Field(
        default=None,
        description="User ID who last updated claim",
    )

    created_at: DateTime = Field(
        default_factory=DateTime.utcnow,
        description="Created timestamp",
    )

    updated_at: DateTime = Field(
        default_factory=DateTime.utcnow,
        description="Updated timestamp",
    )

    # -------------------------
    # Field validators
    # -------------------------

    @field_validator("claim_id")
    @classmethod
    def validate_claim_id(cls, value: str) -> str:
        value = str(value).strip().upper()

        if not CLAIM_ID_PATTERN.match(value):
            raise ValueError("claim_id must follow format CLM-YYYY-0001")

        return value

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)

    @field_validator(
        "employee_id",
        "employee_code",
        "employee_name",
        "claim_type_id",
        "claim_type_code",
        "claim_type_name",
        "title",
    )
    @classmethod
    def validate_required_text_fields(cls, value: str) -> str:
        return normalize_required_text(value)

    @field_validator(
        "external_hrms_id",
        "department_id",
        "department_name",
        "manager_id",
        "manager_name",
        "description",
        "vendor_name",
        "bill_number",
        "project_code",
        "cost_center",
        "sent_back_reason",
        "approved_by",
        "rejected_by",
        "rejection_reason",
        "cancelled_by",
        "cancellation_reason",
        "withdrawn_by",
        "withdrawal_reason",
        "payment_reference",
        "payment_failure_reason",
        "sync_error",
        "employee_notes",
        "internal_notes",
        "created_by",
        "updated_by",
    )
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("claim_type_code")
    @classmethod
    def normalize_claim_type_code(cls, value: str) -> str:
        return normalize_required_text(value, "claim_type_code").upper()

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)

    @field_validator("expense_date")
    @classmethod
    def validate_expense_date(cls, value: Date) -> Date:
        if value > Date.today():
            raise ValueError("expense_date cannot be in the future")

        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []

        for item in value or []:
            tag = str(item).strip().lower().replace(" ", "_")

            if tag and tag not in cleaned:
                cleaned.append(tag)

        return cleaned

    # -------------------------
    # Model validators
    # -------------------------

    @model_validator(mode="after")
    def validate_hrms_read_only_rules(self):
        """
        HRMS-owned records must be identifiable and read-only.
        """
        if self.source == ClaimSource.HRMS:
            if not self.external_hrms_id:
                raise ValueError("external_hrms_id is required when source is hrms")

            if self.is_read_only is not True:
                raise ValueError("is_read_only must be True when source is hrms")

        if self.is_read_only and self.source == ClaimSource.LOCAL:
            raise ValueError("local source claims should not be marked read-only")

        return self

    @model_validator(mode="after")
    def validate_attachment_requirement_snapshot(self):
        """
        Validate only simple snapshot-driven attachment consistency.

        Dynamic rules like amount thresholds and current policy should be checked
        in claim_service.py.
        """
        if self.policy_snapshot.requires_bill and not self.attachments:
            raise ValueError("At least one attachment is required for this claim")

        return self

    @model_validator(mode="after")
    def validate_amount_fields(self):
        """
        Validate approved/paid amount consistency.
        """
        if self.approved_amount is not None:
            if self.approved_amount > self.amount:
                raise ValueError("approved_amount cannot exceed requested amount")

        if self.paid_amount is not None:
            if self.approved_amount is None:
                raise ValueError("approved_amount is required when paid_amount is set")

            if self.paid_amount > self.approved_amount:
                raise ValueError("paid_amount cannot exceed approved_amount")

        return self

    @model_validator(mode="after")
    def validate_cancelled_status(self):
        if self.status == ClaimStatus.CANCELLED:
            if self.cancelled_at is None:
                raise ValueError("cancelled_at is required when status is cancelled")

            if not self.cancellation_reason:
                raise ValueError(
                    "cancellation_reason is required when status is cancelled"
                )

        return self

    @model_validator(mode="after")
    def validate_withdrawn_status(self):
        if self.status == ClaimStatus.WITHDRAWN:
            if self.withdrawn_at is None:
                raise ValueError("withdrawn_at is required when status is withdrawn")

            if not self.withdrawal_reason:
                raise ValueError(
                    "withdrawal_reason is required when status is withdrawn"
                )

        return self

    @model_validator(mode="after")
    def validate_rejected_status(self):
        if self.status == ClaimStatus.REJECTED:
            if self.rejected_at is None:
                raise ValueError("rejected_at is required when status is rejected")

            if not self.rejection_reason:
                raise ValueError("rejection_reason is required when status is rejected")

        return self

    @model_validator(mode="after")
    def validate_sent_back_status(self):
        if self.status == ClaimStatus.SENT_BACK:
            if self.sent_back_at is None:
                raise ValueError("sent_back_at is required when status is sent_back")

            if not self.sent_back_reason:
                raise ValueError(
                    "sent_back_reason is required when status is sent_back"
                )

        return self

    @model_validator(mode="after")
    def validate_approved_status(self):
        approval_statuses = {
            ClaimStatus.MANAGER_APPROVED,
            ClaimStatus.FINANCE_APPROVED,
            ClaimStatus.APPROVED,
        }

        if self.status in approval_statuses:
            if self.approved_amount is None:
                raise ValueError(
                    "approved_amount is required when claim is approved"
                )

            if self.approved_at is None and self.status == ClaimStatus.APPROVED:
                raise ValueError("approved_at is required when status is approved")

        return self

    @model_validator(mode="after")
    def validate_paid_status(self):
        if self.status == ClaimStatus.PAID:
            if self.payment_status != ClaimPaymentStatus.PAID:
                raise ValueError("payment_status must be paid when status is paid")

            if not self.payment_reference:
                raise ValueError("payment_reference is required when status is paid")

            if self.payment_date is None:
                raise ValueError("payment_date is required when status is paid")

            if self.paid_amount is None:
                raise ValueError("paid_amount is required when status is paid")

        return self

    @model_validator(mode="after")
    def validate_failed_status(self):
        if self.status == ClaimStatus.FAILED:
            if self.payment_status != ClaimPaymentStatus.FAILED:
                raise ValueError("payment_status must be failed when status is failed")

            if not self.payment_failure_reason:
                raise ValueError(
                    "payment_failure_reason is required when status is failed"
                )

        return self

    @model_validator(mode="after")
    def validate_approval_steps_order(self):
        """
        Ensure approval step order is unique.
        """
        step_orders = [step.step_order for step in self.approval_steps]

        if len(step_orders) != len(set(step_orders)):
            raise ValueError("approval_steps cannot contain duplicate step_order")

        return self


# -------------------------
# DB model
# -------------------------


class ClaimInDB(Claim):
    """
    Claim model as stored in MongoDB with _id field.
    Used internally by repositories.
    """

    id: Optional[str] = Field(default=None, alias="_id")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


# -------------------------
# Response models
# -------------------------


class ClaimResponse(BaseModel):
    """
    Safe claim response for employee/frontend use.
    """

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    claim_id: str
    company_id: str

    source: ClaimSource
    external_hrms_id: Optional[str] = None
    is_read_only: bool

    employee_id: str
    employee_code: str
    employee_name: str
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    manager_id: Optional[str] = None
    manager_name: Optional[str] = None

    claim_type_id: str
    claim_type_code: str
    claim_type_name: str

    title: str
    description: Optional[str] = None
    amount: float
    currency: str
    expense_date: Date

    vendor_name: Optional[str] = None
    bill_number: Optional[str] = None
    project_code: Optional[str] = None
    cost_center: Optional[str] = None

    attachments: List[ClaimAttachment] = Field(default_factory=list)

    status: ClaimStatus
    priority: ClaimPriority
    submitted_at: Optional[DateTime] = None
    resubmitted_at: Optional[DateTime] = None
    sent_back_at: Optional[DateTime] = None
    sent_back_reason: Optional[str] = None

    approval_steps: List[ClaimApprovalStep] = Field(default_factory=list)
    requires_approval: bool
    current_approval_role: Optional[ClaimApproverRole] = None

    approved_amount: Optional[float] = None
    approved_at: Optional[DateTime] = None
    rejected_at: Optional[DateTime] = None
    rejection_reason: Optional[str] = None

    cancelled_at: Optional[DateTime] = None
    cancellation_reason: Optional[str] = None
    withdrawn_at: Optional[DateTime] = None
    withdrawal_reason: Optional[str] = None

    payment_status: ClaimPaymentStatus
    payment_reference: Optional[str] = None
    payment_date: Optional[Date] = None
    payment_failure_reason: Optional[str] = None
    paid_amount: Optional[float] = None

    employee_notes: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    created_at: DateTime
    updated_at: DateTime


class ClaimPrivateResponse(ClaimResponse):
    """
    Private/admin/HR/finance response.

    Includes internal notes, policy snapshot, sync data, action history,
    and other internal fields.
    """

    policy_snapshot: ClaimPolicySnapshot
    action_history: List[ClaimActionHistory] = Field(default_factory=list)

    approved_by: Optional[str] = None
    rejected_by: Optional[str] = None
    cancelled_by: Optional[str] = None
    withdrawn_by: Optional[str] = None

    synced_to_hrms: bool = False
    synced_at: Optional[DateTime] = None
    sync_error: Optional[str] = None

    internal_notes: Optional[str] = None
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)

    created_by: Optional[str] = None
    updated_by: Optional[str] = None


class ClaimSummary(BaseModel):
    """
    Lightweight claim summary for list views and dashboards.
    """

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    claim_id: str
    company_id: str

    source: ClaimSource
    is_read_only: bool

    employee_id: str
    employee_code: str
    employee_name: str

    department_id: Optional[str] = None
    department_name: Optional[str] = None

    claim_type_id: str
    claim_type_code: str
    claim_type_name: str

    title: str
    amount: float
    approved_amount: Optional[float] = None
    paid_amount: Optional[float] = None
    currency: str

    expense_date: Date
    status: ClaimStatus
    priority: ClaimPriority
    payment_status: ClaimPaymentStatus

    has_attachments: bool = False
    attachment_count: int = 0

    submitted_at: Optional[DateTime] = None
    created_at: DateTime
    updated_at: DateTime


class ClaimStatistics(BaseModel):
    """
    Claim statistics for an employee.
    """

    total_claims: int = Field(default=0)

    draft_claims: int = Field(default=0)
    pending_claims: int = Field(default=0)
    manager_approved_claims: int = Field(default=0)
    finance_approved_claims: int = Field(default=0)
    approved_claims: int = Field(default=0)
    rejected_claims: int = Field(default=0)
    cancelled_claims: int = Field(default=0)
    withdrawn_claims: int = Field(default=0)
    sent_back_claims: int = Field(default=0)
    processing_claims: int = Field(default=0)
    paid_claims: int = Field(default=0)
    failed_claims: int = Field(default=0)

    total_amount_claimed: float = Field(default=0.0)
    total_amount_approved: float = Field(default=0.0)
    total_amount_paid: float = Field(default=0.0)
    pending_amount: float = Field(default=0.0)
    rejected_amount: float = Field(default=0.0)

    monthly_total: float = Field(default=0.0)
    yearly_total: float = Field(default=0.0)

    claim_type_breakdown: Dict[str, int] = Field(default_factory=dict)
    status_breakdown: Dict[str, int] = Field(default_factory=dict)

    currency: str = Field(default="INR")

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)


class ClaimDashboardStatistics(BaseModel):
    """
    Claim dashboard statistics for HR/Admin/Finance/Manager.
    """

    total_claims: int = Field(default=0)

    pending_approval_count: int = Field(default=0)
    pending_manager_approval_count: int = Field(default=0)
    pending_finance_approval_count: int = Field(default=0)

    approved_count: int = Field(default=0)
    rejected_count: int = Field(default=0)
    sent_back_count: int = Field(default=0)
    processing_count: int = Field(default=0)
    paid_count: int = Field(default=0)
    failed_count: int = Field(default=0)

    total_claimed_amount: float = Field(default=0.0)
    total_approved_amount: float = Field(default=0.0)
    total_paid_amount: float = Field(default=0.0)
    pending_payout_amount: float = Field(default=0.0)

    claims_by_type: Dict[str, int] = Field(default_factory=dict)
    claims_by_department: Dict[str, int] = Field(default_factory=dict)
    claims_by_status: Dict[str, int] = Field(default_factory=dict)
    claims_by_source: Dict[str, int] = Field(default_factory=dict)

    monthly_claimed_amount: float = Field(default=0.0)
    yearly_claimed_amount: float = Field(default=0.0)

    read_only_hrms_claims: int = Field(default=0)
    local_claims: int = Field(default=0)
    imported_claims: int = Field(default=0)
    ai_agent_claims: int = Field(default=0)

    currency: str = Field(default="INR")

    generated_at: DateTime = Field(default_factory=DateTime.utcnow)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)