"""
Leave Type master data model.

Stores all leave categories with their business rules.

Employee profiles should reference leave_type_id instead of hard-coded
leave type strings like "sick" or "casual".

Pattern:
- HR/Admin can create and update leave types through API.
- All authenticated users can read active leave types for dropdowns.
- Leave types are soft-deleted using is_active=False.
- Leave type code is unique and stable.
- Each leave type has specific rules: notice period, documentation, limits, carry-forward.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LeaveType(BaseModel):
    """
    Leave Type document model for the leave_types collection.

    Represents leave categories such as:
    - Sick Leave
    - Casual Leave
    - Earned Leave
    - Maternity Leave
    - Paternity Leave
    - Unpaid Leave
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Leave type name, for example Sick Leave or Casual Leave",
    )

    code: str = Field(
        ...,
        min_length=2,
        max_length=20,
        description="Unique short code, for example SICK, CASUAL, EARNED, MATERNITY",
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Leave type description and usage guidelines",
    )

    # -------------------------
    # Grant and limits
    # -------------------------

    default_annual_grant: int = Field(
        ...,
        ge=0,
        description="Default number of days granted per year for new employees",
    )

    max_annual_limit: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum days an employee can take per year. Usually same or higher than annual grant.",
    )

    # -------------------------
    # Approval and documentation
    # -------------------------

    requires_approval: bool = Field(
        default=True,
        description="Whether leave requires manager/HR approval",
    )

    requires_documentation: bool = Field(
        default=False,
        description="Whether leave requires supporting documents such as medical certificate",
    )

    documentation_threshold_days: Optional[int] = Field(
        default=None,
        ge=1,
        description="Number of consecutive days after which documentation becomes mandatory",
    )

    # -------------------------
    # Notice period
    # -------------------------

    min_notice_days: int = Field(
        default=0,
        ge=0,
        description="Minimum advance notice required in days. Example: 0 for sick leave, 7 for planned leave",
    )

    # -------------------------
    # Consecutive days limit
    # -------------------------

    max_consecutive_days: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum consecutive days allowed without special approval",
    )

    # -------------------------
    # Carry forward rules
    # -------------------------

    carry_forward_allowed: bool = Field(
        default=False,
        description="Whether unused leaves can be carried forward to next year",
    )

    max_carry_forward_days: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum days that can be carried forward",
    )

    carry_forward_expiry_months: Optional[int] = Field(
        default=None,
        ge=1,
        le=12,
        description="Months after which carried forward leaves expire",
    )

    # -------------------------
    # Financial rules
    # -------------------------

    is_paid: bool = Field(
        default=True,
        description="Whether this is a paid leave type",
    )

    encashment_allowed: bool = Field(
        default=False,
        description="Whether unused leaves can be encashed",
    )

    max_encashment_days: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum days that can be encashed per year",
    )

    # -------------------------
    # Accrual rules
    # -------------------------

    is_accrued: bool = Field(
        default=False,
        description="Whether leave is accrued monthly instead of granted annually",
    )

    accrual_rate_per_month: Optional[float] = Field(
        default=None,
        ge=0,
        description="Number of days accrued per month if is_accrued=True",
    )

    # -------------------------
    # Eligibility rules
    # -------------------------

    gender_specific: Optional[str] = Field(
        default=None,
        description="Gender restriction: male, female, or None for all",
    )

    available_during_probation: bool = Field(
        default=True,
        description="Whether leave can be taken during probation period",
    )

    probation_grant_percentage: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        description="Percentage of annual grant available during probation",
    )

    # -------------------------
    # Display and status
    # -------------------------

    display_order: int = Field(
        default=0,
        ge=0,
        description="Used to sort leave types in frontend dropdowns",
    )

    is_active: bool = Field(
        default=True,
        description="Soft delete flag. Inactive leave types are hidden from normal dropdowns",
    )

    # -------------------------
    # Audit fields
    # -------------------------

    created_by: Optional[str] = Field(
        default=None,
        description="User ID or employee ID of the HR/Admin who created this leave type",
    )

    updated_by: Optional[str] = Field(
        default=None,
        description="User ID or employee ID of the HR/Admin who last updated this leave type",
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
        Validate leave type code.

        Rules:
        - Uppercase letters, numbers, and underscores only
        - No spaces
        - No special characters except underscore
        """
        value = value.strip().upper()

        if not value:
            raise ValueError("Leave type code cannot be empty")

        if not value.replace("_", "").isalnum():
            raise ValueError(
                "Leave type code can only contain uppercase letters, numbers, and underscores"
            )

        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """
        Normalize leave type name.

        Do not force title case because some names may have specific formatting.
        """
        value = value.strip()

        if not value:
            raise ValueError("Leave type name cannot be empty")

        return value

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

    @field_validator("gender_specific")
    @classmethod
    def validate_gender_specific(cls, value: Optional[str]) -> Optional[str]:
        """
        Validate gender_specific field.
        """
        if value is None:
            return None

        value = value.strip().lower()

        if value not in {"male", "female"}:
            raise ValueError("gender_specific must be 'male', 'female', or None")

        return value

    # -------------------------
    # Cross-field business validation
    # -------------------------

    @model_validator(mode="after")
    def validate_business_rules(self):
        """
        Validate rules that depend on multiple fields.

        These validations prevent invalid master data from entering MongoDB.
        """

        if self.max_annual_limit is not None:
            if self.max_annual_limit < self.default_annual_grant:
                raise ValueError(
                    "max_annual_limit cannot be less than default_annual_grant"
                )

        if self.requires_documentation:
            if self.documentation_threshold_days is None:
                raise ValueError(
                    "documentation_threshold_days is required when requires_documentation=True"
                )
        else:
            if self.documentation_threshold_days is not None:
                raise ValueError(
                    "documentation_threshold_days must be None when requires_documentation=False"
                )

        if self.carry_forward_allowed:
            if self.max_carry_forward_days is None:
                raise ValueError(
                    "max_carry_forward_days is required when carry_forward_allowed=True"
                )
        else:
            if self.max_carry_forward_days is not None:
                raise ValueError(
                    "max_carry_forward_days must be None when carry_forward_allowed=False"
                )

            if self.carry_forward_expiry_months is not None:
                raise ValueError(
                    "carry_forward_expiry_months must be None when carry_forward_allowed=False"
                )

        if self.encashment_allowed:
            if self.max_encashment_days is None:
                raise ValueError(
                    "max_encashment_days is required when encashment_allowed=True"
                )
        else:
            if self.max_encashment_days is not None:
                raise ValueError(
                    "max_encashment_days must be None when encashment_allowed=False"
                )

        if self.is_accrued:
            if self.accrual_rate_per_month is None:
                raise ValueError(
                    "accrual_rate_per_month is required when is_accrued=True"
                )

            if self.default_annual_grant == 0 and self.accrual_rate_per_month == 0:
                raise ValueError(
                    "Either default_annual_grant or accrual_rate_per_month must be greater than 0"
                )
        else:
            if self.accrual_rate_per_month is not None:
                raise ValueError(
                    "accrual_rate_per_month must be None when is_accrued=False"
                )

        if not self.available_during_probation:
            if self.probation_grant_percentage is not None:
                raise ValueError(
                    "probation_grant_percentage must be None when available_during_probation=False"
                )

        return self


class LeaveTypeInDB(LeaveType):
    """
    Leave Type model as stored in MongoDB with _id field.

    Used internally by repositories.
    """

    id: Optional[str] = Field(default=None, alias="_id")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class LeaveTypeResponse(BaseModel):
    """
    Safe leave type response for API output.

    Used by frontend dropdowns, admin pages, and employee leave application pages.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Leave Type ID")
    name: str
    code: str
    description: Optional[str] = None

    default_annual_grant: int
    max_annual_limit: Optional[int] = None

    requires_approval: bool
    requires_documentation: bool
    documentation_threshold_days: Optional[int] = None

    min_notice_days: int
    max_consecutive_days: Optional[int] = None

    carry_forward_allowed: bool
    max_carry_forward_days: Optional[int] = None
    carry_forward_expiry_months: Optional[int] = None

    is_paid: bool
    encashment_allowed: bool
    max_encashment_days: Optional[int] = None

    is_accrued: bool
    accrual_rate_per_month: Optional[float] = None

    gender_specific: Optional[str] = None

    available_during_probation: bool
    probation_grant_percentage: Optional[int] = None

    display_order: int
    is_active: bool

    created_at: datetime
    updated_at: datetime


class LeaveTypeListItem(BaseModel):
    """
    Lightweight leave type item for dropdown lists.

    Minimal fields for performance when loading dropdowns.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    default_annual_grant: int
    min_notice_days: int
    is_paid: bool
    is_active: bool


class LeaveTypeDropdownResponse(BaseModel):
    """
    Very lightweight leave type response for frontend dropdowns.

    Use this when employee leave form only needs selectable active leave types.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    min_notice_days: int
    requires_documentation: bool
    documentation_threshold_days: Optional[int] = None
    is_paid: bool


class LeaveTypeDetailResponse(LeaveTypeResponse):
    """
    Leave type response with additional usage statistics.

    Used for admin dashboard showing how many employees are using each leave type.
    """

    total_employees_granted: int = Field(
        default=0,
        ge=0,
        description="Number of employees with this leave type in their balance",
    )

    total_applications_this_year: int = Field(
        default=0,
        ge=0,
        description="Total leave applications for this type in current year",
    )


class LeaveTypeStatistics(BaseModel):
    """
    Statistics response for leave type dashboard.

    These values will be calculated in repository/service layer later.
    """

    total_leave_types: int = Field(default=0, ge=0)
    active_leave_types: int = Field(default=0, ge=0)
    inactive_leave_types: int = Field(default=0, ge=0)
    paid_leave_types: int = Field(default=0, ge=0)
    unpaid_leave_types: int = Field(default=0, ge=0)
    approval_required_leave_types: int = Field(default=0, ge=0)
    documentation_required_leave_types: int = Field(default=0, ge=0)
    carry_forward_enabled_leave_types: int = Field(default=0, ge=0)
    encashment_enabled_leave_types: int = Field(default=0, ge=0)