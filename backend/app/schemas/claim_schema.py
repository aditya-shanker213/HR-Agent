"""
Claim request/response schemas for API layer.

These schemas define what the API accepts and returns.
They are separate from models, which define MongoDB document structure.

Pattern:
- Request schemas: what frontend/API clients send
- Response schemas: what frontend/API clients receive
- Service layer fills trusted snapshots like employee, claim type, and policy data
- Repository layer handles MongoDB only

Important:
- Do not let frontend directly provide employee snapshot or policy snapshot
  during normal claim creation. Service should derive those from DB.
- HRMS/import schemas are separate because those records may be read-only.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime as DateTime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.models.claim_model import (
    ALLOWED_ATTACHMENT_EXTENSIONS,
    MAX_ATTACHMENT_SIZE_BYTES,
    ClaimActionHistory,
    ClaimActionType,
    ClaimApprovalStatus,
    ClaimApprovalStep,
    ClaimApproverRole,
    ClaimAttachment,
    ClaimDashboardStatistics,
    ClaimPaymentStatus,
    ClaimPolicySnapshot,
    ClaimPriority,
    ClaimPrivateResponse,
    ClaimResponse,
    ClaimSource,
    ClaimStatistics,
    ClaimStatus,
    ClaimSummary,
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


def normalize_required_text(value: str, field_name: str = "value") -> str:
    """
    Strip required text fields.
    """
    value = str(value).strip()

    if not value:
        raise ValueError(f"{field_name} cannot be empty")

    return value


def normalize_currency(value: Optional[str]) -> str:
    """
    Normalize currency code.
    """
    if value is None:
        return "INR"

    value = str(value).strip().upper()

    if not value:
        return "INR"

    if not value.isalpha() or len(value) != 3:
        raise ValueError("currency must be a valid 3-letter code, for example INR")

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


def normalize_tags(value: Optional[List[str]]) -> List[str]:
    """
    Normalize tags:
    - lowercase
    - trim spaces
    - replace spaces with underscore
    - remove duplicates
    """
    if not value:
        return []

    cleaned: List[str] = []

    for item in value:
        tag = str(item).strip().lower().replace(" ", "_")

        if tag and tag not in cleaned:
            cleaned.append(tag)

    return cleaned


def validate_not_future_date(value: Optional[Date], field_name: str) -> Optional[Date]:
    """
    Validate date is not in future.
    """
    if value is None:
        return None

    if value > Date.today():
        raise ValueError(f"{field_name} cannot be in the future")

    return value


# ============================================================================
# Attachment Schemas
# ============================================================================


class AddClaimAttachmentRequest(BaseModel):
    """
    Request schema for adding claim attachment metadata.

    POST /api/v1/claims/{claim_id}/attachments

    Note:
    Actual file upload should happen separately through file upload or signed URL.
    This endpoint stores only metadata.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
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
        value = str(value).strip().lower()

        if not value:
            raise ValueError("file_type cannot be empty")

        if "/" in value:
            value = value.split("/")[-1]

        value = value.replace(".", "").strip()

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


class VerifyClaimAttachmentRequest(BaseModel):
    """
    Request schema for HR/finance attachment verification.

    POST /api/v1/claims/{claim_id}/attachments/{attachment_index}/verify
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    is_verified: bool = Field(
        ...,
        description="Whether attachment is verified",
    )

    comments: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional verification comments",
    )

    @field_validator("comments")
    @classmethod
    def clean_comments(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


# ============================================================================
# Create / Draft / Update Claim Requests
# ============================================================================


class CreateClaimRequest(BaseModel):
    """
    Request schema for creating a new claim.

    POST /api/v1/claims

    Service layer should:
    - get employee from current user
    - fill employee snapshot
    - validate claim type
    - fill claim type snapshot
    - capture claim policy snapshot
    - generate claim_id
    - build approval steps
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    claim_type_id: str = Field(
        ...,
        min_length=1,
        description="Claim type reference from master data",
    )

    title: str = Field(
        ...,
        min_length=5,
        max_length=200,
        description="Short claim title",
    )

    description: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Detailed claim description",
    )

    amount: float = Field(
        ...,
        gt=0,
        description="Claim amount",
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
        description="Vendor/merchant name",
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

    priority: ClaimPriority = Field(
        default=ClaimPriority.NORMAL,
        description="Claim urgency",
    )

    employee_notes: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Employee-visible notes",
    )

    tags: List[str] = Field(
        default_factory=list,
        description="Tags for categorization",
    )

    attachments: List[AddClaimAttachmentRequest] = Field(
        default_factory=list,
        description="Optional attachment metadata during claim creation",
    )

    @field_validator("claim_type_id", "title")
    @classmethod
    def validate_required_text_fields(cls, value: str) -> str:
        return normalize_required_text(value)

    @field_validator(
        "description",
        "vendor_name",
        "bill_number",
        "project_code",
        "cost_center",
        "employee_notes",
    )
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)

    @field_validator("expense_date")
    @classmethod
    def validate_expense_date(cls, value: Date) -> Date:
        result = validate_not_future_date(value, "expense_date")
        assert result is not None
        return result

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: Optional[List[str]]) -> List[str]:
        return normalize_tags(value)


class CreateClaimDraftRequest(BaseModel):
    """
    Request schema for saving a claim draft.

    POST /api/v1/claims/draft

    Drafts allow partial claim data.
    Service should still link current employee and generate claim_id.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    claim_type_id: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Claim type reference",
    )

    title: Optional[str] = Field(
        default=None,
        min_length=5,
        max_length=200,
    )

    description: Optional[str] = Field(
        default=None,
        max_length=2000,
    )

    amount: Optional[float] = Field(
        default=None,
        gt=0,
    )

    currency: str = Field(
        default="INR",
        min_length=3,
        max_length=3,
    )

    expense_date: Optional[Date] = None

    vendor_name: Optional[str] = Field(default=None, max_length=150)
    bill_number: Optional[str] = Field(default=None, max_length=100)
    project_code: Optional[str] = Field(default=None, max_length=100)
    cost_center: Optional[str] = Field(default=None, max_length=100)

    priority: ClaimPriority = Field(default=ClaimPriority.NORMAL)

    employee_notes: Optional[str] = Field(default=None, max_length=2000)

    tags: List[str] = Field(default_factory=list)

    @field_validator(
        "claim_type_id",
        "title",
        "description",
        "vendor_name",
        "bill_number",
        "project_code",
        "cost_center",
        "employee_notes",
    )
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)

    @field_validator("expense_date")
    @classmethod
    def validate_expense_date(cls, value: Optional[Date]) -> Optional[Date]:
        return validate_not_future_date(value, "expense_date")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: Optional[List[str]]) -> List[str]:
        return normalize_tags(value)


class UpdateClaimRequest(BaseModel):
    """
    Request schema for updating editable claim fields.

    PATCH /api/v1/claims/{claim_id}

    Service layer must enforce:
    - read-only HRMS claims cannot be locally edited
    - only draft/sent_back/resubmittable claims can be edited
    - employee can only update own allowed claims
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    claim_type_id: Optional[str] = Field(default=None, min_length=1)

    title: Optional[str] = Field(default=None, min_length=5, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)

    amount: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    expense_date: Optional[Date] = None

    vendor_name: Optional[str] = Field(default=None, max_length=150)
    bill_number: Optional[str] = Field(default=None, max_length=100)
    project_code: Optional[str] = Field(default=None, max_length=100)
    cost_center: Optional[str] = Field(default=None, max_length=100)

    priority: Optional[ClaimPriority] = None
    employee_notes: Optional[str] = Field(default=None, max_length=2000)
    tags: Optional[List[str]] = None

    @field_validator(
        "claim_type_id",
        "title",
        "description",
        "vendor_name",
        "bill_number",
        "project_code",
        "cost_center",
        "employee_notes",
    )
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        return normalize_currency(value)

    @field_validator("expense_date")
    @classmethod
    def validate_expense_date(cls, value: Optional[Date]) -> Optional[Date]:
        return validate_not_future_date(value, "expense_date")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None

        return normalize_tags(value)

    @model_validator(mode="after")
    def validate_at_least_one_field(self):
        if not any(
            value is not None
            for value in [
                self.claim_type_id,
                self.title,
                self.description,
                self.amount,
                self.currency,
                self.expense_date,
                self.vendor_name,
                self.bill_number,
                self.project_code,
                self.cost_center,
                self.priority,
                self.employee_notes,
                self.tags,
            ]
        ):
            raise ValueError("At least one field must be provided for update")

        return self


# ============================================================================
# Submit / Resubmit / Withdraw / Cancel Requests
# ============================================================================


class SubmitClaimRequest(BaseModel):
    """
    Request schema for submitting a draft claim.

    POST /api/v1/claims/{claim_id}/submit
    """

    model_config = ConfigDict(extra="forbid")

    confirm: bool = Field(
        ...,
        description="Must be true to submit claim",
    )

    @field_validator("confirm")
    @classmethod
    def validate_confirm(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Confirmation is required to submit claim")

        return value


class ResubmitClaimRequest(BaseModel):
    """
    Request schema for resubmitting a sent-back claim.

    POST /api/v1/claims/{claim_id}/resubmit
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    comments: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Employee comments while resubmitting",
    )

    confirm: bool = Field(
        ...,
        description="Must be true to resubmit claim",
    )

    @field_validator("comments")
    @classmethod
    def clean_comments(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("confirm")
    @classmethod
    def validate_confirm(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Confirmation is required to resubmit claim")

        return value


class CancelClaimRequest(BaseModel):
    """
    Request schema for cancelling a claim.

    POST /api/v1/claims/{claim_id}/cancel
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    cancellation_reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Reason for cancellation",
    )

    @field_validator("cancellation_reason")
    @classmethod
    def validate_cancellation_reason(cls, value: str) -> str:
        return normalize_required_text(value, "cancellation_reason")


class WithdrawClaimRequest(BaseModel):
    """
    Request schema for withdrawing a claim.

    POST /api/v1/claims/{claim_id}/withdraw
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    withdrawal_reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Reason for withdrawal",
    )

    @field_validator("withdrawal_reason")
    @classmethod
    def validate_withdrawal_reason(cls, value: str) -> str:
        return normalize_required_text(value, "withdrawal_reason")


# ============================================================================
# Approval Requests
# ============================================================================


class ApproveClaimRequest(BaseModel):
    """
    Request schema for approving a claim approval step.

    POST /api/v1/claims/{claim_id}/approve

    Service layer should determine whether actor is manager/finance/HR/admin
    and which approval step they are acting on.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    approved_amount: Optional[float] = Field(
        default=None,
        gt=0,
        description="Approved amount if different from requested amount",
    )

    comments: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Approval comments",
    )

    @field_validator("comments")
    @classmethod
    def clean_comments(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class RejectClaimRequest(BaseModel):
    """
    Request schema for rejecting a claim.

    POST /api/v1/claims/{claim_id}/reject
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    rejection_reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Reason for rejection",
    )

    @field_validator("rejection_reason")
    @classmethod
    def validate_rejection_reason(cls, value: str) -> str:
        return normalize_required_text(value, "rejection_reason")


class SendBackClaimRequest(BaseModel):
    """
    Request schema for sending a claim back to employee for correction.

    POST /api/v1/claims/{claim_id}/send-back
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    sent_back_reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Reason for sending claim back",
    )

    comments: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional internal comments",
    )

    @field_validator("sent_back_reason")
    @classmethod
    def validate_sent_back_reason(cls, value: str) -> str:
        return normalize_required_text(value, "sent_back_reason")

    @field_validator("comments")
    @classmethod
    def clean_comments(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class SkipApprovalStepRequest(BaseModel):
    """
    Request schema for skipping an approval step.

    Usually Admin/HR only.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    step_order: int = Field(..., ge=1)
    reason: str = Field(..., min_length=10, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return normalize_required_text(value, "reason")


# ============================================================================
# Payment Requests
# ============================================================================


class StartClaimPaymentProcessingRequest(BaseModel):
    """
    Request schema for marking a claim as payment processing.

    POST /api/v1/claims/{claim_id}/payment/start
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    comments: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("comments")
    @classmethod
    def clean_comments(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class MarkClaimPaidRequest(BaseModel):
    """
    Request schema for marking a claim as paid.

    POST /api/v1/claims/{claim_id}/payment/paid
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    payment_reference: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Payment transaction reference",
    )

    payment_date: Date = Field(
        ...,
        description="Payment date",
    )

    paid_amount: float = Field(
        ...,
        gt=0,
        description="Actually paid amount",
    )

    comments: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Payment comments",
    )

    @field_validator("payment_reference")
    @classmethod
    def validate_payment_reference(cls, value: str) -> str:
        return normalize_required_text(value, "payment_reference")

    @field_validator("payment_date")
    @classmethod
    def validate_payment_date(cls, value: Date) -> Date:
        result = validate_not_future_date(value, "payment_date")
        assert result is not None
        return result

    @field_validator("comments")
    @classmethod
    def clean_comments(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class MarkClaimPaymentFailedRequest(BaseModel):
    """
    Request schema for marking claim payment as failed.

    POST /api/v1/claims/{claim_id}/payment/failed
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    payment_failure_reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Reason payment failed",
    )

    comments: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("payment_failure_reason")
    @classmethod
    def validate_failure_reason(cls, value: str) -> str:
        return normalize_required_text(value, "payment_failure_reason")

    @field_validator("comments")
    @classmethod
    def clean_comments(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class UpdatePaymentStatusRequest(BaseModel):
    """
    Generic payment update request.

    You may keep this if your route uses one payment endpoint.
    Prefer specific endpoints for production clarity.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    payment_status: ClaimPaymentStatus

    payment_reference: Optional[str] = Field(default=None, max_length=200)
    payment_date: Optional[Date] = None
    paid_amount: Optional[float] = Field(default=None, gt=0)
    payment_failure_reason: Optional[str] = Field(default=None, max_length=1000)

    comments: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("payment_reference", "payment_failure_reason", "comments")
    @classmethod
    def clean_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("payment_date")
    @classmethod
    def validate_payment_date(cls, value: Optional[Date]) -> Optional[Date]:
        return validate_not_future_date(value, "payment_date")

    @model_validator(mode="after")
    def validate_payment_status_requirements(self):
        if self.payment_status == ClaimPaymentStatus.PAID:
            if not self.payment_reference:
                raise ValueError("payment_reference is required when payment_status is paid")

            if self.payment_date is None:
                raise ValueError("payment_date is required when payment_status is paid")

            if self.paid_amount is None:
                raise ValueError("paid_amount is required when payment_status is paid")

        if self.payment_status == ClaimPaymentStatus.FAILED:
            if not self.payment_failure_reason:
                raise ValueError(
                    "payment_failure_reason is required when payment_status is failed"
                )

        return self


# ============================================================================
# HRMS / Import Requests
# ============================================================================


class ImportClaimFromHRMSRequest(BaseModel):
    """
    Request schema for importing/read-only HRMS claim records.

    This should usually be used by HRMS sync service or admin-only route,
    not by normal employees.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    company_id: str = Field(default="default", min_length=1, max_length=100)

    external_hrms_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="External HRMS claim ID",
    )

    claim_id: Optional[str] = Field(
        default=None,
        description="Optional existing claim ID from HRMS. Service can generate if absent.",
    )

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

    title: str = Field(..., min_length=5, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)

    amount: float = Field(..., gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    expense_date: Date

    status: ClaimStatus = Field(default=ClaimStatus.PENDING)
    priority: ClaimPriority = Field(default=ClaimPriority.NORMAL)

    approved_amount: Optional[float] = Field(default=None, ge=0)
    paid_amount: Optional[float] = Field(default=None, ge=0)

    payment_status: ClaimPaymentStatus = Field(default=ClaimPaymentStatus.NOT_STARTED)
    payment_reference: Optional[str] = Field(default=None, max_length=200)
    payment_date: Optional[Date] = None

    attachments: List[AddClaimAttachmentRequest] = Field(default_factory=list)

    extra_metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)

    @field_validator(
        "external_hrms_id",
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
        "claim_id",
        "department_id",
        "department_name",
        "manager_id",
        "manager_name",
        "description",
        "payment_reference",
    )
    @classmethod
    def clean_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("claim_type_code")
    @classmethod
    def normalize_claim_type_code(cls, value: str) -> str:
        return normalize_required_text(value, "claim_type_code").upper()

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)

    @field_validator("expense_date", "payment_date")
    @classmethod
    def validate_dates(cls, value: Optional[Date]) -> Optional[Date]:
        return validate_not_future_date(value, "date")

    @model_validator(mode="after")
    def validate_amounts(self):
        if self.approved_amount is not None and self.approved_amount > self.amount:
            raise ValueError("approved_amount cannot exceed amount")

        if self.paid_amount is not None:
            if self.approved_amount is None:
                raise ValueError("approved_amount is required when paid_amount is set")

            if self.paid_amount > self.approved_amount:
                raise ValueError("paid_amount cannot exceed approved_amount")

        return self


# ============================================================================
# Query / Filter Schemas
# ============================================================================


class ClaimListFilters(BaseModel):
    """
    Query parameters for listing claims.

    GET /api/v1/claims
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    company_id: str = Field(default="default", min_length=1, max_length=100)

    status: Optional[ClaimStatus] = None
    source: Optional[ClaimSource] = None
    claim_type_id: Optional[str] = None
    claim_type_code: Optional[str] = None

    employee_id: Optional[str] = None
    employee_code: Optional[str] = None

    department_id: Optional[str] = None
    manager_id: Optional[str] = None

    priority: Optional[ClaimPriority] = None
    payment_status: Optional[ClaimPaymentStatus] = None

    is_read_only: Optional[bool] = None

    from_date: Optional[Date] = None
    to_date: Optional[Date] = None

    min_amount: Optional[float] = Field(default=None, ge=0)
    max_amount: Optional[float] = Field(default=None, ge=0)

    search: Optional[str] = Field(default=None, max_length=200)

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    sort_by: str = Field(
        default="created_at",
        description="created_at, expense_date, amount, status",
    )

    sort_order: str = Field(
        default="desc",
        description="asc or desc",
    )

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)

    @field_validator(
        "claim_type_id",
        "claim_type_code",
        "employee_id",
        "employee_code",
        "department_id",
        "manager_id",
        "search",
        "sort_by",
        "sort_order",
    )
    @classmethod
    def clean_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("claim_type_code")
    @classmethod
    def normalize_claim_type_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        value = normalize_optional_text(value)
        return value.upper() if value else None

    @field_validator("sort_order")
    @classmethod
    def validate_sort_order(cls, value: Optional[str]) -> str:
        value = (value or "desc").strip().lower()

        if value not in {"asc", "desc"}:
            raise ValueError("sort_order must be asc or desc")

        return value

    @field_validator("sort_by")
    @classmethod
    def validate_sort_by(cls, value: Optional[str]) -> str:
        value = (value or "created_at").strip().lower()

        allowed = {
            "created_at",
            "updated_at",
            "expense_date",
            "amount",
            "approved_amount",
            "paid_amount",
            "status",
            "priority",
        }

        if value not in allowed:
            raise ValueError(f"sort_by must be one of: {', '.join(sorted(allowed))}")

        return value

    @model_validator(mode="after")
    def validate_date_and_amount_ranges(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date cannot be after to_date")

        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("min_amount cannot be greater than max_amount")

        return self


class PendingApprovalsFilters(BaseModel):
    """
    Query parameters for pending approvals.

    GET /api/v1/claims/pending-approvals
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    company_id: str = Field(default="default", min_length=1, max_length=100)

    approver_role: Optional[ClaimApproverRole] = None
    claim_type_id: Optional[str] = None
    department_id: Optional[str] = None
    priority: Optional[ClaimPriority] = None

    min_amount: Optional[float] = Field(default=None, ge=0)
    max_amount: Optional[float] = Field(default=None, ge=0)

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)

    @field_validator("claim_type_id", "department_id")
    @classmethod
    def clean_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_amount_range(self):
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("min_amount cannot be greater than max_amount")

        return self


class ClaimDashboardFilters(BaseModel):
    """
    Query parameters for claim dashboard.

    GET /api/v1/claims/dashboard
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    company_id: str = Field(default="default", min_length=1, max_length=100)

    from_date: Optional[Date] = None
    to_date: Optional[Date] = None

    department_id: Optional[str] = None
    manager_id: Optional[str] = None
    claim_type_id: Optional[str] = None

    currency: str = Field(default="INR", min_length=3, max_length=3)

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)

    @field_validator("department_id", "manager_id", "claim_type_id")
    @classmethod
    def clean_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.from_date and self.to_date and self.from_date > self.to_date:
            raise ValueError("from_date cannot be after to_date")

        return self


# ============================================================================
# Validation / Limit Check Schemas
# ============================================================================


class ValidateClaimRequest(BaseModel):
    """
    Request schema for validating a claim before submission.

    POST /api/v1/claims/validate
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    claim_type_id: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    expense_date: Date
    attachment_count: int = Field(default=0, ge=0)

    @field_validator("claim_type_id")
    @classmethod
    def validate_claim_type_id(cls, value: str) -> str:
        return normalize_required_text(value, "claim_type_id")

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)

    @field_validator("expense_date")
    @classmethod
    def validate_expense_date(cls, value: Date) -> Date:
        result = validate_not_future_date(value, "expense_date")
        assert result is not None
        return result


class ClaimValidationResponse(BaseModel):
    """
    Response for claim validation before submission.
    """

    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    limit_check: Dict[str, Any] = Field(default_factory=dict)
    duplicate_check: Dict[str, Any] = Field(default_factory=dict)
    bill_requirement: Dict[str, Any] = Field(default_factory=dict)
    policy_check: Dict[str, Any] = Field(default_factory=dict)
    approval_preview: Dict[str, Any] = Field(default_factory=dict)


class ClaimLimitCheckResponse(BaseModel):
    """
    Response for checking claim limits.

    GET /api/v1/claims/check-limit/{claim_type_id}
    """

    claim_type_id: str
    claim_type_code: Optional[str] = None
    claim_type_name: str

    currency: str = "INR"

    monthly_limit: Optional[float] = None
    monthly_used_amount: float = 0.0
    monthly_remaining_amount: Optional[float] = None

    yearly_limit: Optional[float] = None
    yearly_used_amount: float = 0.0
    yearly_remaining_amount: Optional[float] = None

    max_claim_amount: Optional[float] = None

    can_claim: bool
    message: str

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)


# ============================================================================
# Response Wrapper Schemas
# ============================================================================


class ClaimCreatedResponse(BaseModel):
    """
    Response after creating a claim.
    """

    message: str = Field(default="Claim created successfully")
    claim_id: str
    claim: ClaimResponse


class ClaimDraftCreatedResponse(BaseModel):
    """
    Response after creating a claim draft.
    """

    message: str = Field(default="Claim draft created successfully")
    claim_id: str
    claim: ClaimResponse


class ClaimUpdatedResponse(BaseModel):
    """
    Response after updating a claim.
    """

    message: str = Field(default="Claim updated successfully")
    claim: ClaimResponse


class ClaimSubmittedResponse(BaseModel):
    """
    Response after submitting a claim.
    """

    message: str = Field(default="Claim submitted successfully")
    claim_id: str
    status: ClaimStatus
    submitted_at: DateTime
    claim: ClaimResponse


class ClaimActionResponse(BaseModel):
    """
    Standard response for claim actions like approve/reject/cancel/withdraw.
    """

    success: bool = True
    message: str
    claim_id: str
    old_status: Optional[ClaimStatus] = None
    new_status: ClaimStatus
    timestamp: DateTime = Field(default_factory=DateTime.utcnow)
    claim: Optional[ClaimResponse] = None


class ClaimPrivateActionResponse(BaseModel):
    """
    Standard private response for HR/Admin/Finance actions.
    """

    success: bool = True
    message: str
    claim_id: str
    old_status: Optional[ClaimStatus] = None
    new_status: ClaimStatus
    timestamp: DateTime = Field(default_factory=DateTime.utcnow)
    claim: Optional[ClaimPrivateResponse] = None


class ClaimListResponse(BaseModel):
    """
    Paginated claim list response.
    """

    items: List[ClaimSummary] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0


class ClaimDashboardResponse(BaseModel):
    """
    Comprehensive dashboard response.

    GET /api/v1/claims/dashboard
    """

    statistics: ClaimDashboardStatistics
    recent_claims: List[ClaimSummary] = Field(default_factory=list)
    pending_approvals: List[ClaimSummary] = Field(default_factory=list)
    pending_approvals_count: int = 0


class ClaimStatisticsResponse(BaseModel):
    """
    Claim statistics response.

    GET /api/v1/claims/statistics
    """

    statistics: ClaimStatistics


class ClaimApprovalStepsResponse(BaseModel):
    """
    Response for claim approval workflow steps.
    """

    claim_id: str
    status: ClaimStatus
    current_approval_role: Optional[ClaimApproverRole] = None
    approval_steps: List[ClaimApprovalStep] = Field(default_factory=list)


class ClaimActionHistoryResponse(BaseModel):
    """
    Response for claim action history.
    """

    claim_id: str
    action_history: List[ClaimActionHistory] = Field(default_factory=list)


class ClaimAttachmentsResponse(BaseModel):
    """
    Response for claim attachments.
    """

    claim_id: str
    attachments: List[ClaimAttachment] = Field(default_factory=list)


class ClaimAttachmentAddedResponse(BaseModel):
    """
    Response after adding an attachment.
    """

    message: str = Field(default="Attachment added successfully")
    claim_id: str
    attachment: ClaimAttachment


class ClaimAttachmentVerifiedResponse(BaseModel):
    """
    Response after verifying an attachment.
    """

    message: str = Field(default="Attachment verification updated successfully")
    claim_id: str
    attachment_index: int
    is_verified: bool


# ============================================================================
# Bulk Action Schemas
# ============================================================================


class BulkClaimActionRequest(BaseModel):
    """
    Request for bulk claim actions.

    Example:
    POST /api/v1/claims/bulk-approve
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    claim_ids: List[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of claim IDs to process",
    )

    comments: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Bulk action comments",
    )

    @field_validator("claim_ids")
    @classmethod
    def validate_claim_ids(cls, value: List[str]) -> List[str]:
        cleaned: List[str] = []

        for item in value:
            claim_id = normalize_required_text(item, "claim_id").upper()

            if claim_id not in cleaned:
                cleaned.append(claim_id)

        if not cleaned:
            raise ValueError("At least one claim_id is required")

        return cleaned

    @field_validator("comments")
    @classmethod
    def clean_comments(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class BulkClaimApproveRequest(BulkClaimActionRequest):
    """
    Request for bulk approving claims.
    """


class BulkClaimRejectRequest(BulkClaimActionRequest):
    """
    Request for bulk rejecting claims.
    """

    rejection_reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Reason for bulk rejection",
    )

    @field_validator("rejection_reason")
    @classmethod
    def validate_rejection_reason(cls, value: str) -> str:
        return normalize_required_text(value, "rejection_reason")


class BulkClaimActionResponse(BaseModel):
    """
    Response for bulk claim actions.
    """

    success: bool
    message: str
    processed_count: int
    failed_count: int
    results: List[Dict[str, Any]] = Field(default_factory=list)


# ============================================================================
# HRMS Sync Response Schemas
# ============================================================================


class ClaimHRMSImportResponse(BaseModel):
    """
    Response after importing one HRMS claim.
    """

    message: str = Field(default="Claim imported from HRMS successfully")
    claim_id: str
    external_hrms_id: str
    is_read_only: bool
    claim: ClaimPrivateResponse


class ClaimHRMSSyncStatusResponse(BaseModel):
    """
    Response for HRMS sync status.
    """

    claim_id: str
    source: ClaimSource
    external_hrms_id: Optional[str] = None
    is_read_only: bool
    synced_to_hrms: bool
    synced_at: Optional[DateTime] = None
    sync_error: Optional[str] = None