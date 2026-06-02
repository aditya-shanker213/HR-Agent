"""
Claim Type master data model.

Stores all reimbursement/expense categories with business rules.
Employee claims should reference claim_type_id instead of hard-coded strings
such as "travel", "food", or "medical".

Pattern:
- HR/Admin can create and update claim types through API.
- All authenticated users can read active claim types for dropdowns.
- Claim types are soft-deleted using is_active=False.
- Claim type code is unique and stable.
- Each claim type has different limits, bill rules, approval rules, and payout rules.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ClaimType(BaseModel):
    """
    Claim Type document model for the claim_types collection.

    Represents reimbursement categories such as:
    - Travel Expenses
    - Food & Beverages
    - Medical Reimbursement
    - Internet Reimbursement
    - Fuel Expenses
    - Work From Home Setup
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Claim type name, for example Travel Expenses or Medical Reimbursement",
    )

    code: str = Field(
        ...,
        min_length=2,
        max_length=20,
        description="Unique short code, for example TRAVEL, FOOD, MEDICAL, INTERNET",
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="What expenses are covered under this claim type",
    )

    # -------------------------
    # Limit rules
    # -------------------------

    default_annual_limit: int = Field(
        ...,
        ge=0,
        description="Default annual claim limit amount per employee",
    )

    default_monthly_limit: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional monthly claim limit amount per employee",
    )

    max_claim_amount: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum amount allowed in a single claim",
    )

    min_claim_amount: Optional[int] = Field(
        default=None,
        ge=0,
        description="Minimum amount required to submit a claim",
    )

    # -------------------------
    # Bill/document rules
    # -------------------------

    requires_bill: bool = Field(
        default=True,
        description="Whether bill/receipt is mandatory for this claim type",
    )

    bill_threshold: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Bill is required only if claim amount exceeds this threshold. "
            "If requires_bill=True and bill_threshold=None, bill is always required."
        ),
    )

    allowed_file_types: list[str] = Field(
        default_factory=lambda: ["pdf", "jpg", "jpeg", "png"],
        description="Allowed bill attachment file extensions",
    )

    max_file_size_mb: int = Field(
        default=5,
        ge=1,
        le=25,
        description="Maximum bill attachment size in MB",
    )

    # -------------------------
    # Approval rules
    # -------------------------

    requires_approval: bool = Field(
        default=True,
        description="Whether this claim type requires approval workflow",
    )

    approval_threshold: Optional[int] = Field(
        default=None,
        ge=0,
        description="Manager approval required if claim exceeds this amount",
    )

    finance_approval_threshold: Optional[int] = Field(
        default=None,
        ge=0,
        description="Finance approval required if claim exceeds this amount",
    )

    auto_approve_below: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Legacy/reference threshold only. "
            "This field must not auto-approve claims. "
            "Claim approval must go through manager/finance/HR workflow."
        ),
    )

    # -------------------------
    # Reimbursement rules
    # -------------------------

    reimbursement_percentage: int = Field(
        default=100,
        ge=0,
        le=100,
        description="Percentage of approved claim amount reimbursed",
    )

    is_taxable: bool = Field(
        default=False,
        description="Whether reimbursement is taxable",
    )

    currency: str = Field(
        default="INR",
        min_length=3,
        max_length=3,
        description="Currency code such as INR, USD, EUR",
    )

    # -------------------------
    # Eligibility and display
    # -------------------------

    available_during_probation: bool = Field(
        default=True,
        description="Whether employees can submit this claim during probation",
    )

    display_order: int = Field(
        default=0,
        ge=0,
        description="Used to sort claim types in frontend dropdowns",
    )

    is_active: bool = Field(
        default=True,
        description="Soft delete flag. Inactive claim types are hidden from normal dropdowns",
    )

    # -------------------------
    # Audit fields
    # -------------------------

    created_by: Optional[str] = Field(
        default=None,
        description="User ID or employee ID of the HR/Admin who created this claim type",
    )

    updated_by: Optional[str] = Field(
        default=None,
        description="User ID or employee ID of the HR/Admin who last updated this claim type",
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Creation timestamp",
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp",
    )

    # -------------------------
    # Field validators
    # -------------------------

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        """
        Validate claim type code.

        Rules:
        - Uppercase letters, numbers, and underscores only
        - No spaces
        - No special characters except underscore
        """
        value = value.strip().upper()

        if not value:
            raise ValueError("Claim type code cannot be empty")

        if not value.replace("_", "").isalnum():
            raise ValueError(
                "Claim type code can only contain uppercase letters, numbers, and underscores"
            )

        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """
        Normalize claim type name.

        Do not force title case because names like WFH Setup, R&D Travel,
        or IT Hardware should keep their intended formatting.
        """
        value = value.strip()

        if not value:
            raise ValueError("Claim type name cannot be empty")

        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        """
        Normalize currency code.
        """
        value = value.strip().upper()

        if not value.isalpha() or len(value) != 3:
            raise ValueError("currency must be a valid 3-letter code, for example INR")

        return value

    @field_validator("allowed_file_types")
    @classmethod
    def validate_allowed_file_types(cls, value: list[str]) -> list[str]:
        """
        Normalize allowed file extensions.
        """
        if not value:
            raise ValueError("allowed_file_types cannot be empty")

        normalized: list[str] = []
        for item in value:
            extension = item.strip().lower().replace(".", "")

            if not extension:
                continue

            if not extension.isalnum():
                raise ValueError("allowed_file_types can contain only file extensions")

            if extension not in normalized:
                normalized.append(extension)

        if not normalized:
            raise ValueError("allowed_file_types cannot be empty")

        return normalized

    @field_validator(
        "description",
        "created_by",
        "updated_by",
    )
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        """
        Strip optional text fields.

        Empty strings become None so MongoDB does not store useless "" values.
        """
        if value is None:
            return None

        value = value.strip()
        return value or None

    # -------------------------
    # Cross-field business validation
    # -------------------------

    @model_validator(mode="after")
    def validate_business_rules(self):
        """
        Validate rules that depend on multiple fields.

        These validations prevent invalid claim configuration from entering MongoDB.
        """

        if self.default_monthly_limit is not None:
            if self.default_monthly_limit > self.default_annual_limit:
                raise ValueError(
                    "default_monthly_limit cannot be greater than default_annual_limit"
                )

        if self.max_claim_amount is not None:
            if self.max_claim_amount > self.default_annual_limit:
                raise ValueError(
                    "max_claim_amount cannot be greater than default_annual_limit"
                )

        if self.min_claim_amount is not None and self.max_claim_amount is not None:
            if self.min_claim_amount > self.max_claim_amount:
                raise ValueError(
                    "min_claim_amount cannot be greater than max_claim_amount"
                )

        if not self.requires_bill and self.bill_threshold is not None:
            raise ValueError(
                "bill_threshold must be None when requires_bill=False"
            )

        if not self.requires_approval:
            if self.approval_threshold is not None:
                raise ValueError(
                    "approval_threshold must be None when requires_approval=False"
                )

            if self.finance_approval_threshold is not None:
                raise ValueError(
                    "finance_approval_threshold must be None when requires_approval=False"
                )

        if self.approval_threshold is not None:
            if self.max_claim_amount is not None:
                if self.approval_threshold > self.max_claim_amount:
                    raise ValueError(
                        "approval_threshold cannot be greater than max_claim_amount"
                    )

        if self.finance_approval_threshold is not None:
            if self.approval_threshold is not None:
                if self.finance_approval_threshold < self.approval_threshold:
                    raise ValueError(
                        "finance_approval_threshold cannot be less than approval_threshold"
                    )

            if self.max_claim_amount is not None:
                if self.finance_approval_threshold > self.max_claim_amount:
                    raise ValueError(
                        "finance_approval_threshold cannot be greater than max_claim_amount"
                    )

        # auto_approve_below is legacy/reference only.
        # It must not control approval workflow.
        # No business validation is required for approval behavior here.

        return self


class ClaimTypeInDB(ClaimType):
    """
    Claim Type model as stored in MongoDB with _id field.

    Used internally by repositories.
    """

    id: Optional[str] = Field(default=None, alias="_id")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ClaimTypeResponse(BaseModel):
    """
    Safe claim type response for API output.

    Used by frontend dropdowns, admin pages, and employee claim submission pages.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Claim Type ID")
    name: str
    code: str
    description: Optional[str] = None

    default_annual_limit: int
    default_monthly_limit: Optional[int] = None
    max_claim_amount: Optional[int] = None
    min_claim_amount: Optional[int] = None

    requires_bill: bool
    bill_threshold: Optional[int] = None
    allowed_file_types: list[str]
    max_file_size_mb: int

    requires_approval: bool
    approval_threshold: Optional[int] = None
    finance_approval_threshold: Optional[int] = None
    auto_approve_below: Optional[int] = None

    reimbursement_percentage: int
    is_taxable: bool
    currency: str

    available_during_probation: bool
    display_order: int
    is_active: bool

    created_at: datetime
    updated_at: datetime


class ClaimTypeListItem(BaseModel):
    """
    Lightweight claim type item for admin list and dropdown use.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    default_annual_limit: int
    max_claim_amount: Optional[int] = None
    requires_bill: bool
    requires_approval: bool
    is_active: bool


class ClaimTypeDropdownResponse(BaseModel):
    """
    Very lightweight claim type response for frontend dropdowns.

    Use this when employee claim form only needs selectable active claim types.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    default_annual_limit: int
    max_claim_amount: Optional[int] = None
    min_claim_amount: Optional[int] = None
    requires_bill: bool
    bill_threshold: Optional[int] = None
    allowed_file_types: list[str]
    max_file_size_mb: int
    currency: str


class ClaimTypeDetailResponse(ClaimTypeResponse):
    """
    Claim type response with additional usage statistics.

    Used for admin dashboard showing how much each claim type is used.
    """

    total_employees_using: int = Field(
        default=0,
        ge=0,
        description="Number of employees who have used this claim type",
    )

    total_claims_this_year: int = Field(
        default=0,
        ge=0,
        description="Total claim applications for this type in current year",
    )

    total_amount_claimed: float = Field(
        default=0.0,
        ge=0,
        description="Total amount claimed across all employees",
    )

    total_amount_approved: float = Field(
        default=0.0,
        ge=0,
        description="Total approved amount across all employees",
    )

    average_claim_amount: float = Field(
        default=0.0,
        ge=0,
        description="Average claim amount",
    )


class ClaimTypeStatistics(BaseModel):
    """
    Statistics response for claim type dashboard.

    These values will be calculated in repository/service layer later.
    """

    total_claim_types: int = Field(default=0, ge=0)
    active_claim_types: int = Field(default=0, ge=0)
    inactive_claim_types: int = Field(default=0, ge=0)
    bill_required_claim_types: int = Field(default=0, ge=0)
    approval_required_claim_types: int = Field(default=0, ge=0)
    legacy_auto_approval_configured_claim_types: int = Field(
        default=0,
        ge=0,
        description=(
            "Legacy/reference count only. "
            "This does not mean claims are auto-approved."
        ),
    )
    taxable_claim_types: int = Field(default=0, ge=0)
    probation_available_claim_types: int = Field(default=0, ge=0)
