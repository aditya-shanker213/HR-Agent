"""
Company Settings schemas - Request/Response models for API endpoints.

This file contains Pydantic schemas for:
- Creating company settings
- Updating full company settings
- Patching company settings
- Updating specific configuration sections
- API responses
- Summary responses
- Status responses

Pattern:
- Request schemas for POST/PATCH
- Response schemas for GET
- Section-specific schemas for partial updates

Important:
- Schemas are API contracts.
- Models are MongoDB document structure.
- Repositories handle MongoDB operations.
- Services should merge partial updates with existing settings before validating.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


# -------------------------
# Constants
# -------------------------

VALID_WEEKDAYS = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}

VALID_PAY_CYCLES = {
    "monthly",
    "bi-weekly",
    "weekly",
}

VALID_COMPANY_SIZES = {
    "startup",
    "small",
    "medium",
    "large",
    "enterprise",
}

VALID_SECTION_NAMES = {
    "company_info",
    "system",
    "work_week",
    "leave_policy",
    "payroll",
    "claim_policy",
}


# -------------------------
# Shared helpers
# -------------------------


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    """
    Strip optional text.

    Empty string becomes None.
    """
    if value is None:
        return None

    value = str(value).strip()
    return value or None


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
    """
    if value is None:
        return "INR"

    value = str(value).strip().upper()

    if not value:
        return "INR"

    if not value.isalpha() or len(value) != 3:
        raise ValueError("currency must be a valid 3-letter code, for example INR")

    return value


def normalize_weekday(value: Optional[str]) -> Optional[str]:
    """
    Normalize one weekday value.
    """
    if value is None:
        return None

    value = str(value).strip().lower()

    if not value:
        return None

    if value not in VALID_WEEKDAYS:
        raise ValueError(
            f"Invalid weekday: {value}. Must be one of: {', '.join(sorted(VALID_WEEKDAYS))}"
        )

    return value


def normalize_weekday_list(value: list[str]) -> list[str]:
    """
    Normalize weekday list and remove duplicates.
    """
    if not value:
        raise ValueError("weekday list cannot be empty")

    cleaned: list[str] = []

    for day in value:
        normalized = normalize_weekday(day)

        if normalized and normalized not in cleaned:
            cleaned.append(normalized)

    if not cleaned:
        raise ValueError("weekday list cannot be empty")

    return cleaned


def normalize_file_formats(value: Optional[list[str]]) -> list[str]:
    """
    Normalize file extensions.

    Example:
    [".PDF", "jpg", " JPG "] -> ["pdf", "jpg"]
    """
    if not value:
        return ["pdf", "jpg", "jpeg", "png"]

    cleaned: list[str] = []

    for item in value:
        extension = str(item).strip().lower().replace(".", "")

        if not extension:
            continue

        if not extension.isalnum():
            raise ValueError("file formats can contain only file extensions")

        if extension not in cleaned:
            cleaned.append(extension)

    if not cleaned:
        raise ValueError("allowed_bill_formats cannot be empty")

    return cleaned


# -------------------------
# Full Nested Configuration Schemas
# -------------------------


class WorkWeekConfigSchema(BaseModel):
    """
    Work week configuration schema.

    Used for full create/update of work week configuration.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    working_days: list[str] = Field(
        default_factory=lambda: [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
        ],
        description="List of working days in lowercase",
    )

    weekend_days: list[str] = Field(
        default_factory=lambda: ["saturday", "sunday"],
        description="List of weekend days in lowercase",
    )

    working_hours_per_day: float = Field(
        default=8.0,
        ge=1.0,
        le=24.0,
        description="Standard working hours per day",
    )

    half_day_on: Optional[str] = Field(
        default=None,
        description="Optional half-day weekday, for example saturday",
    )

    half_day_hours: float = Field(
        default=4.0,
        ge=1.0,
        le=12.0,
        description="Working hours on half-day",
    )

    flexible_working_hours: bool = Field(
        default=False,
        description="Whether flexible working hours are enabled",
    )

    @field_validator("working_days", "weekend_days")
    @classmethod
    def validate_days(cls, value: list[str]) -> list[str]:
        return normalize_weekday_list(value)

    @field_validator("half_day_on")
    @classmethod
    def validate_half_day_on(cls, value: Optional[str]) -> Optional[str]:
        return normalize_weekday(value)

    @model_validator(mode="after")
    def validate_work_week_rules(self):
        working_set = set(self.working_days)
        weekend_set = set(self.weekend_days)

        overlap = working_set.intersection(weekend_set)

        if overlap:
            raise ValueError(
                f"working_days and weekend_days cannot overlap: {', '.join(sorted(overlap))}"
            )

        if self.half_day_on:
            if self.half_day_on not in working_set:
                raise ValueError("half_day_on must be one of the working_days")

            if self.half_day_hours >= self.working_hours_per_day:
                raise ValueError(
                    "half_day_hours must be less than working_hours_per_day"
                )

        return self


class LeavePolicyConfigSchema(BaseModel):
    """
    Leave policy configuration schema.

    Used for full create/update of leave policy configuration.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    leave_year_start_month: int = Field(default=1, ge=1, le=12)

    max_carryforward_days: int = Field(default=10, ge=0, le=365)
    carryforward_expiry_months: int = Field(default=3, ge=0, le=24)

    allow_leave_encashment: bool = Field(default=True)
    min_encashment_days: int = Field(default=5, ge=0)
    max_encashment_days: int = Field(default=30, ge=0)

    probation_period_days: int = Field(default=90, ge=0, le=730)
    allow_leave_during_probation: bool = Field(default=True)
    probation_leave_limit_days: int = Field(default=3, ge=0)

    min_notice_days: int = Field(default=1, ge=0)
    max_advance_days: int = Field(default=90, ge=1, le=730)

    allow_backdated_leave: bool = Field(default=False)
    backdated_leave_days_limit: int = Field(default=0, ge=0, le=365)

    allow_half_day_leave: bool = Field(default=True)
    half_day_deduction: float = Field(default=0.5, ge=0.0, le=1.0)

    allow_negative_balance: bool = Field(default=False)
    max_negative_balance_days: int = Field(default=0, ge=0, le=365)

    @model_validator(mode="after")
    def validate_leave_policy_rules(self):
        if not self.allow_leave_encashment:
            if self.min_encashment_days != 0 or self.max_encashment_days != 0:
                raise ValueError(
                    "min_encashment_days and max_encashment_days must be 0 when allow_leave_encashment=False"
                )

        if self.allow_leave_encashment:
            if self.max_encashment_days < self.min_encashment_days:
                raise ValueError(
                    "max_encashment_days cannot be less than min_encashment_days"
                )

        if not self.allow_leave_during_probation:
            if self.probation_leave_limit_days != 0:
                raise ValueError(
                    "probation_leave_limit_days must be 0 when allow_leave_during_probation=False"
                )

        if not self.allow_backdated_leave:
            if self.backdated_leave_days_limit != 0:
                raise ValueError(
                    "backdated_leave_days_limit must be 0 when allow_backdated_leave=False"
                )

        if not self.allow_half_day_leave:
            if self.half_day_deduction != 0:
                raise ValueError(
                    "half_day_deduction must be 0 when allow_half_day_leave=False"
                )

        if not self.allow_negative_balance:
            if self.max_negative_balance_days != 0:
                raise ValueError(
                    "max_negative_balance_days must be 0 when allow_negative_balance=False"
                )

        if self.min_notice_days > self.max_advance_days:
            raise ValueError("min_notice_days cannot be greater than max_advance_days")

        return self


class PayrollConfigSchema(BaseModel):
    """
    Payroll configuration schema.

    Used for full create/update of payroll configuration.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    pay_cycle: Literal["monthly", "bi-weekly", "weekly"] = Field(default="monthly")

    pay_day: int = Field(
        default=1,
        ge=1,
        le=31,
        description="Day of month for salary payment when pay_cycle is monthly",
    )

    financial_year_start_month: int = Field(default=4, ge=1, le=12)

    currency: str = Field(default="INR", min_length=3, max_length=3)

    enable_tds: bool = Field(default=True)

    enable_pf: bool = Field(default=True)
    pf_rate_employee: float = Field(default=12.0, ge=0.0, le=100.0)
    pf_rate_employer: float = Field(default=12.0, ge=0.0, le=100.0)

    enable_esi: bool = Field(default=False)
    esi_rate_employee: float = Field(default=0.0, ge=0.0, le=100.0)
    esi_rate_employer: float = Field(default=0.0, ge=0.0, le=100.0)

    enable_professional_tax: bool = Field(default=False)
    professional_tax_state: Optional[str] = Field(default=None, max_length=50)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)

    @field_validator("professional_tax_state")
    @classmethod
    def normalize_professional_tax_state(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        return normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_payroll_rules(self):
        if self.pay_cycle != "monthly" and self.pay_day != 1:
            raise ValueError(
                "pay_day should be 1 when pay_cycle is weekly or bi-weekly"
            )

        if not self.enable_pf:
            if self.pf_rate_employee != 0 or self.pf_rate_employer != 0:
                raise ValueError("PF rates must be 0 when enable_pf=False")

        if not self.enable_esi:
            if self.esi_rate_employee != 0 or self.esi_rate_employer != 0:
                raise ValueError("ESI rates must be 0 when enable_esi=False")

        if self.enable_professional_tax and not self.professional_tax_state:
            raise ValueError(
                "professional_tax_state is required when enable_professional_tax=True"
            )

        if not self.enable_professional_tax and self.professional_tax_state is not None:
            raise ValueError(
                "professional_tax_state must be None when enable_professional_tax=False"
            )

        return self


class ClaimPolicyConfigSchema(BaseModel):
    """
    Claim policy configuration schema.

    Used for full create/update of claim policy configuration.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    require_bill_above: float = Field(default=500.0, ge=0.0)

    max_bill_file_size_mb: int = Field(default=5, ge=1, le=50)

    allowed_bill_formats: list[str] = Field(
        default_factory=lambda: ["pdf", "jpg", "jpeg", "png"],
        description="Allowed file formats for bills",
    )

    enable_manager_approval: bool = Field(default=True)
    manager_approval_threshold: float = Field(default=5000.0, ge=0.0)

    enable_finance_approval: bool = Field(default=True)
    finance_approval_threshold: float = Field(default=20000.0, ge=0.0)

    enable_auto_approval: bool = Field(
        default=False,
        description=(
            "Deprecated/disabled. "
            "Claims must go through manager/finance/HR approval workflow."
        ),
    )
    auto_approval_threshold: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Deprecated/disabled. "
            "Must remain 0 because claim auto approval is not used."
        ),
    )

    claim_submission_deadline_days: int = Field(default=30, ge=1, le=365)

    allow_advance_claim: bool = Field(default=False)

    reimbursement_processing_days: int = Field(default=7, ge=1, le=90)

    @field_validator("allowed_bill_formats")
    @classmethod
    def validate_allowed_bill_formats(cls, value: list[str]) -> list[str]:
        return normalize_file_formats(value)

    @model_validator(mode="after")
    def validate_claim_policy_rules(self):
        if not self.enable_manager_approval:
            if self.manager_approval_threshold != 0:
                raise ValueError(
                    "manager_approval_threshold must be 0 when enable_manager_approval=False"
                )

        if not self.enable_finance_approval:
            if self.finance_approval_threshold != 0:
                raise ValueError(
                    "finance_approval_threshold must be 0 when enable_finance_approval=False"
                )

        if self.enable_auto_approval:
            raise ValueError(
                "Claim auto approval is disabled. Claims require human approval."
            )

        if self.auto_approval_threshold != 0:
            raise ValueError(
                "auto_approval_threshold must be 0 because claim auto approval is disabled"
            )

        if self.enable_manager_approval and self.enable_finance_approval:
            if self.finance_approval_threshold < self.manager_approval_threshold:
                raise ValueError(
                    "finance_approval_threshold cannot be less than manager_approval_threshold"
                )

        return self


class CompanyInfoSchema(BaseModel):
    """
    Company information schema.

    Used for full create/update of company information.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    company_name: str = Field(..., min_length=2, max_length=200)

    company_short_name: Optional[str] = Field(default=None, max_length=50)

    email: EmailStr

    phone: Optional[str] = Field(default=None, max_length=20)

    website: Optional[str] = Field(default=None, max_length=200)

    address_line1: str = Field(..., min_length=2, max_length=200)
    address_line2: Optional[str] = Field(default=None, max_length=200)

    city: str = Field(..., min_length=2, max_length=100)
    state: str = Field(..., min_length=2, max_length=100)
    pincode: str = Field(..., min_length=2, max_length=20)
    country: str = Field(default="India", min_length=2, max_length=100)

    pan: Optional[str] = Field(default=None, max_length=20)
    tan: Optional[str] = Field(default=None, max_length=20)
    gstin: Optional[str] = Field(default=None, max_length=20)

    pf_registration_number: Optional[str] = Field(default=None, max_length=50)
    esi_registration_number: Optional[str] = Field(default=None, max_length=50)

    industry: Optional[str] = Field(default=None, max_length=100)

    company_size: Optional[
        Literal["startup", "small", "medium", "large", "enterprise"]
    ] = Field(default=None)

    @field_validator(
        "company_short_name",
        "phone",
        "website",
        "address_line2",
        "pan",
        "tan",
        "gstin",
        "pf_registration_number",
        "esi_registration_number",
        "industry",
    )
    @classmethod
    def clean_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        value = normalize_optional_text(value)

        if value is None:
            return None

        allowed_chars = set("+0123456789 -")

        if any(char not in allowed_chars for char in value):
            raise ValueError("phone can contain only digits, spaces, +, and -")

        return value

    @field_validator("pan", "tan", "gstin")
    @classmethod
    def normalize_tax_ids(cls, value: Optional[str]) -> Optional[str]:
        value = normalize_optional_text(value)

        if value is None:
            return None

        return value.upper()


class SystemConfigSchema(BaseModel):
    """
    System configuration schema.

    Used for full create/update of system-level HR settings.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    timezone: str = Field(default="Asia/Kolkata", min_length=3, max_length=100)
    locale: str = Field(default="en-IN", min_length=2, max_length=20)
    default_country: str = Field(default="India", min_length=2, max_length=100)
    default_location: Optional[str] = Field(default=None, max_length=100)

    allow_employee_self_service: bool = Field(default=True)
    allow_ai_assistant: bool = Field(default=True)

    @field_validator("timezone", "locale", "default_country", "default_location")
    @classmethod
    def clean_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


# -------------------------
# Partial Nested Configuration Schemas
# -------------------------


class WorkWeekConfigPatchSchema(BaseModel):
    """
    Partial work week update schema.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    working_days: Optional[list[str]] = None
    weekend_days: Optional[list[str]] = None
    working_hours_per_day: Optional[float] = Field(default=None, ge=1.0, le=24.0)
    half_day_on: Optional[str] = None
    half_day_hours: Optional[float] = Field(default=None, ge=1.0, le=12.0)
    flexible_working_hours: Optional[bool] = None

    @field_validator("working_days", "weekend_days")
    @classmethod
    def validate_day_lists(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None

        return normalize_weekday_list(value)

    @field_validator("half_day_on")
    @classmethod
    def validate_half_day_on(cls, value: Optional[str]) -> Optional[str]:
        return normalize_weekday(value)

    @model_validator(mode="after")
    def validate_partial_work_week_rules(self):
        if self.working_days is not None and self.weekend_days is not None:
            overlap = set(self.working_days).intersection(set(self.weekend_days))

            if overlap:
                raise ValueError(
                    f"working_days and weekend_days cannot overlap: {', '.join(sorted(overlap))}"
                )

        if self.half_day_hours is not None and self.working_hours_per_day is not None:
            if self.half_day_hours >= self.working_hours_per_day:
                raise ValueError(
                    "half_day_hours must be less than working_hours_per_day"
                )

        return self


class LeavePolicyConfigPatchSchema(BaseModel):
    """
    Partial leave policy update schema.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    leave_year_start_month: Optional[int] = Field(default=None, ge=1, le=12)

    max_carryforward_days: Optional[int] = Field(default=None, ge=0, le=365)
    carryforward_expiry_months: Optional[int] = Field(default=None, ge=0, le=24)

    allow_leave_encashment: Optional[bool] = None
    min_encashment_days: Optional[int] = Field(default=None, ge=0)
    max_encashment_days: Optional[int] = Field(default=None, ge=0)

    probation_period_days: Optional[int] = Field(default=None, ge=0, le=730)
    allow_leave_during_probation: Optional[bool] = None
    probation_leave_limit_days: Optional[int] = Field(default=None, ge=0)

    min_notice_days: Optional[int] = Field(default=None, ge=0)
    max_advance_days: Optional[int] = Field(default=None, ge=1, le=730)

    allow_backdated_leave: Optional[bool] = None
    backdated_leave_days_limit: Optional[int] = Field(default=None, ge=0, le=365)

    allow_half_day_leave: Optional[bool] = None
    half_day_deduction: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    allow_negative_balance: Optional[bool] = None
    max_negative_balance_days: Optional[int] = Field(default=None, ge=0, le=365)

    @model_validator(mode="after")
    def validate_partial_leave_rules(self):
        if (
            self.min_encashment_days is not None
            and self.max_encashment_days is not None
            and self.max_encashment_days < self.min_encashment_days
        ):
            raise ValueError(
                "max_encashment_days cannot be less than min_encashment_days"
            )

        if (
            self.min_notice_days is not None
            and self.max_advance_days is not None
            and self.min_notice_days > self.max_advance_days
        ):
            raise ValueError("min_notice_days cannot be greater than max_advance_days")

        return self


class PayrollConfigPatchSchema(BaseModel):
    """
    Partial payroll update schema.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    pay_cycle: Optional[Literal["monthly", "bi-weekly", "weekly"]] = None
    pay_day: Optional[int] = Field(default=None, ge=1, le=31)
    financial_year_start_month: Optional[int] = Field(default=None, ge=1, le=12)

    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)

    enable_tds: Optional[bool] = None

    enable_pf: Optional[bool] = None
    pf_rate_employee: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    pf_rate_employer: Optional[float] = Field(default=None, ge=0.0, le=100.0)

    enable_esi: Optional[bool] = None
    esi_rate_employee: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    esi_rate_employer: Optional[float] = Field(default=None, ge=0.0, le=100.0)

    enable_professional_tax: Optional[bool] = None
    professional_tax_state: Optional[str] = Field(default=None, max_length=50)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        return normalize_currency(value)

    @field_validator("professional_tax_state")
    @classmethod
    def clean_professional_tax_state(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_partial_payroll_rules(self):
        if self.pay_cycle is not None and self.pay_day is not None:
            if self.pay_cycle != "monthly" and self.pay_day != 1:
                raise ValueError(
                    "pay_day should be 1 when pay_cycle is weekly or bi-weekly"
                )

        return self


class ClaimPolicyConfigPatchSchema(BaseModel):
    """
    Partial claim policy update schema.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    require_bill_above: Optional[float] = Field(default=None, ge=0.0)
    max_bill_file_size_mb: Optional[int] = Field(default=None, ge=1, le=50)
    allowed_bill_formats: Optional[list[str]] = None

    enable_manager_approval: Optional[bool] = None
    manager_approval_threshold: Optional[float] = Field(default=None, ge=0.0)

    enable_finance_approval: Optional[bool] = None
    finance_approval_threshold: Optional[float] = Field(default=None, ge=0.0)

    enable_auto_approval: Optional[bool] = Field(
        default=None,
        description="Deprecated/disabled. Passing True is not allowed.",
    )
    auto_approval_threshold: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Deprecated/disabled. Must be None or 0.",
    )

    claim_submission_deadline_days: Optional[int] = Field(
        default=None,
        ge=1,
        le=365,
    )

    allow_advance_claim: Optional[bool] = None

    reimbursement_processing_days: Optional[int] = Field(default=None, ge=1, le=90)

    @field_validator("allowed_bill_formats")
    @classmethod
    def validate_allowed_bill_formats(
        cls,
        value: Optional[list[str]],
    ) -> Optional[list[str]]:
        if value is None:
            return None

        return normalize_file_formats(value)

    @model_validator(mode="after")
    def validate_partial_claim_rules(self):
        if self.enable_auto_approval is True:
            raise ValueError(
                "Claim auto approval is disabled. Claims require human approval."
            )

        if self.auto_approval_threshold not in (None, 0):
            raise ValueError(
                "auto_approval_threshold must be 0 because claim auto approval is disabled"
            )

        if (
            self.finance_approval_threshold is not None
            and self.manager_approval_threshold is not None
            and self.finance_approval_threshold < self.manager_approval_threshold
        ):
            raise ValueError(
                "finance_approval_threshold cannot be less than manager_approval_threshold"
            )

        return self


class CompanyInfoPatchSchema(BaseModel):
    """
    Partial company information update schema.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    company_name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    company_short_name: Optional[str] = Field(default=None, max_length=50)

    email: Optional[EmailStr] = None

    phone: Optional[str] = Field(default=None, max_length=20)
    website: Optional[str] = Field(default=None, max_length=200)

    address_line1: Optional[str] = Field(default=None, min_length=2, max_length=200)
    address_line2: Optional[str] = Field(default=None, max_length=200)

    city: Optional[str] = Field(default=None, min_length=2, max_length=100)
    state: Optional[str] = Field(default=None, min_length=2, max_length=100)
    pincode: Optional[str] = Field(default=None, min_length=2, max_length=20)
    country: Optional[str] = Field(default=None, min_length=2, max_length=100)

    pan: Optional[str] = Field(default=None, max_length=20)
    tan: Optional[str] = Field(default=None, max_length=20)
    gstin: Optional[str] = Field(default=None, max_length=20)

    pf_registration_number: Optional[str] = Field(default=None, max_length=50)
    esi_registration_number: Optional[str] = Field(default=None, max_length=50)

    industry: Optional[str] = Field(default=None, max_length=100)

    company_size: Optional[
        Literal["startup", "small", "medium", "large", "enterprise"]
    ] = None

    @field_validator(
        "company_short_name",
        "phone",
        "website",
        "address_line2",
        "country",
        "pan",
        "tan",
        "gstin",
        "pf_registration_number",
        "esi_registration_number",
        "industry",
    )
    @classmethod
    def clean_optional_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        value = normalize_optional_text(value)

        if value is None:
            return None

        allowed_chars = set("+0123456789 -")

        if any(char not in allowed_chars for char in value):
            raise ValueError("phone can contain only digits, spaces, +, and -")

        return value

    @field_validator("pan", "tan", "gstin")
    @classmethod
    def normalize_tax_ids(cls, value: Optional[str]) -> Optional[str]:
        value = normalize_optional_text(value)

        if value is None:
            return None

        return value.upper()


class SystemConfigPatchSchema(BaseModel):
    """
    Partial system configuration update schema.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    timezone: Optional[str] = Field(default=None, min_length=3, max_length=100)
    locale: Optional[str] = Field(default=None, min_length=2, max_length=20)
    default_country: Optional[str] = Field(default=None, min_length=2, max_length=100)
    default_location: Optional[str] = Field(default=None, max_length=100)

    allow_employee_self_service: Optional[bool] = None
    allow_ai_assistant: Optional[bool] = None

    @field_validator("timezone", "locale", "default_country", "default_location")
    @classmethod
    def clean_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


# -------------------------
# Request Schemas
# -------------------------


class CreateCompanySettingsRequest(BaseModel):
    """
    Request schema for creating company settings.

    Used by:
        POST /api/v1/company-settings

    Required role:
        Admin
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    company_id: str = Field(
        default="default",
        min_length=2,
        max_length=100,
        description="Company identifier",
    )

    company_info: CompanyInfoSchema = Field(
        ...,
        description="General company information",
    )

    system: SystemConfigSchema = Field(
        default_factory=SystemConfigSchema,
        description="System-level HR configuration",
    )

    work_week: WorkWeekConfigSchema = Field(
        default_factory=WorkWeekConfigSchema,
        description="Work week configuration",
    )

    leave_policy: LeavePolicyConfigSchema = Field(
        default_factory=LeavePolicyConfigSchema,
        description="Leave policy configuration",
    )

    payroll: PayrollConfigSchema = Field(
        default_factory=PayrollConfigSchema,
        description="Payroll configuration",
    )

    claim_policy: ClaimPolicyConfigSchema = Field(
        default_factory=ClaimPolicyConfigSchema,
        description="Claim policy configuration",
    )

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)


class InitializeCompanySettingsRequest(BaseModel):
    """
    Minimal first-time company settings initialization request.

    Used by:
        POST /api/v1/company-settings/initialize

    Required role:
        Admin
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    company_id: str = Field(default="default", min_length=2, max_length=100)

    company_name: str = Field(..., min_length=2, max_length=200)
    email: EmailStr
    address_line1: str = Field(..., min_length=2, max_length=200)
    city: str = Field(..., min_length=2, max_length=100)
    state: str = Field(..., min_length=2, max_length=100)
    pincode: str = Field(..., min_length=2, max_length=20)
    country: str = Field(default="India", min_length=2, max_length=100)

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)


class UpdateCompanySettingsRequest(BaseModel):
    """
    Full section update schema for company settings.

    Note:
    Each provided section replaces the existing section.
    Service should merge existing settings with this request before model validation.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    company_info: Optional[CompanyInfoSchema] = None
    system: Optional[SystemConfigSchema] = None
    work_week: Optional[WorkWeekConfigSchema] = None
    leave_policy: Optional[LeavePolicyConfigSchema] = None
    payroll: Optional[PayrollConfigSchema] = None
    claim_policy: Optional[ClaimPolicyConfigSchema] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def validate_at_least_one_field(self):
        if not any(
            value is not None
            for value in [
                self.company_info,
                self.system,
                self.work_week,
                self.leave_policy,
                self.payroll,
                self.claim_policy,
                self.is_active,
            ]
        ):
            raise ValueError("At least one field must be provided for update")

        return self


class PatchCompanySettingsRequest(BaseModel):
    """
    Partial nested update schema for company settings.

    Note:
    These sections are partial. Service should merge with existing settings
    before validating with CompanySettings model.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    company_info: Optional[CompanyInfoPatchSchema] = None
    system: Optional[SystemConfigPatchSchema] = None
    work_week: Optional[WorkWeekConfigPatchSchema] = None
    leave_policy: Optional[LeavePolicyConfigPatchSchema] = None
    payroll: Optional[PayrollConfigPatchSchema] = None
    claim_policy: Optional[ClaimPolicyConfigPatchSchema] = None

    @model_validator(mode="after")
    def validate_at_least_one_section(self):
        if not any(
            value is not None
            for value in [
                self.company_info,
                self.system,
                self.work_week,
                self.leave_policy,
                self.payroll,
                self.claim_policy,
            ]
        ):
            raise ValueError("At least one settings section must be provided")

        return self


class UpdateCompanySettingsSectionRequest(BaseModel):
    """
    Dynamic section update request.

    Used when route is:
        PATCH /api/v1/company-settings/sections/{section_name}

    The service should validate section_data using the correct section schema.
    """

    model_config = ConfigDict(extra="forbid")

    section_name: Literal[
        "company_info",
        "system",
        "work_week",
        "leave_policy",
        "payroll",
        "claim_policy",
    ]

    section_data: dict = Field(
        ...,
        description="Full section data to replace existing section",
    )


class PatchCompanySettingsSectionRequest(BaseModel):
    """
    Dynamic section patch request.

    Used when route is:
        PATCH /api/v1/company-settings/sections/{section_name}/patch
    """

    model_config = ConfigDict(extra="forbid")

    section_name: Literal[
        "company_info",
        "system",
        "work_week",
        "leave_policy",
        "payroll",
        "claim_policy",
    ]

    section_data: dict = Field(
        ...,
        description="Partial section data to patch existing section",
    )


# -------------------------
# Section-Specific Request Schemas
# -------------------------


class UpdateCompanyInfoRequest(CompanyInfoSchema):
    """
    Replace full company_info section.
    """


class PatchCompanyInfoRequest(CompanyInfoPatchSchema):
    """
    Patch company_info section.
    """


class UpdateSystemConfigRequest(SystemConfigSchema):
    """
    Replace full system section.
    """


class PatchSystemConfigRequest(SystemConfigPatchSchema):
    """
    Patch system section.
    """


class UpdateWorkWeekRequest(WorkWeekConfigSchema):
    """
    Replace full work_week section.
    """


class PatchWorkWeekRequest(WorkWeekConfigPatchSchema):
    """
    Patch work_week section.
    """


class UpdateLeavePolicyRequest(LeavePolicyConfigSchema):
    """
    Replace full leave_policy section.
    """


class PatchLeavePolicyRequest(LeavePolicyConfigPatchSchema):
    """
    Patch leave_policy section.
    """


class UpdatePayrollRequest(PayrollConfigSchema):
    """
    Replace full payroll section.
    """


class PatchPayrollRequest(PayrollConfigPatchSchema):
    """
    Patch payroll section.
    """


class UpdateClaimPolicyRequest(ClaimPolicyConfigSchema):
    """
    Replace full claim_policy section.
    """


class PatchClaimPolicyRequest(ClaimPolicyConfigPatchSchema):
    """
    Patch claim_policy section.
    """


# -------------------------
# Query Schemas
# -------------------------


class CompanySettingsQuery(BaseModel):
    """
    Query parameters for company settings endpoints.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    company_id: str = Field(default="default", min_length=2, max_length=100)

    include_inactive: bool = Field(
        default=False,
        description="Whether inactive settings can be returned",
    )

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)


class CompanySettingsSectionQuery(BaseModel):
    """
    Query parameters for section endpoint.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    company_id: str = Field(default="default", min_length=2, max_length=100)

    section_name: Literal[
        "company_info",
        "system",
        "work_week",
        "leave_policy",
        "payroll",
        "claim_policy",
    ]

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        return normalize_company_id(value)


# -------------------------
# Response Schemas
# -------------------------


class CompanySettingsResponse(BaseModel):
    """
    Full company settings response.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str

    company_info: CompanyInfoSchema
    system: SystemConfigSchema
    work_week: WorkWeekConfigSchema
    leave_policy: LeavePolicyConfigSchema
    payroll: PayrollConfigSchema
    claim_policy: ClaimPolicyConfigSchema

    is_active: bool

    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    created_at: datetime
    updated_at: datetime


class CompanySettingsSummaryResponse(BaseModel):
    """
    Lightweight company settings summary response.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str

    company_name: str
    currency: str
    pay_cycle: str
    timezone: str

    leave_year_start_month: int
    financial_year_start_month: int
    probation_period_days: int

    working_days: list[str]
    weekend_days: list[str]

    is_active: bool


class CompanySettingsCreatedResponse(BaseModel):
    """
    Response after creating company settings.
    """

    message: str = Field(default="Company settings created successfully")
    settings_id: str
    settings: CompanySettingsResponse


class CompanySettingsUpdatedResponse(BaseModel):
    """
    Response after updating company settings.
    """

    message: str = Field(default="Company settings updated successfully")
    settings: CompanySettingsResponse


class CompanySettingsInitializedResponse(BaseModel):
    """
    Response after initializing company settings.
    """

    message: str = Field(default="Company settings initialized successfully")
    settings_id: str
    settings: CompanySettingsResponse


class CompanySettingsStatusResponse(BaseModel):
    """
    Response after activating/deactivating company settings.
    """

    message: str
    company_id: str
    is_active: bool


class CompanySettingsSectionResponse(BaseModel):
    """
    Response for one settings section.
    """

    company_id: str

    section_name: Literal[
        "company_info",
        "system",
        "work_week",
        "leave_policy",
        "payroll",
        "claim_policy",
    ]

    section_data: dict


class CompanySettingsExistsResponse(BaseModel):
    """
    Response for settings existence/status check.
    """

    company_id: str
    exists: bool
    is_active: bool


class CompanySettingsValidationResponse(BaseModel):
    """
    Response for validating settings payload.
    """

    is_valid: bool
    errors: list[dict] = Field(default_factory=list)


class CompanySettingsDeletedResponse(BaseModel):
    """
    Alias-style response for deactivate operation.

    We soft-delete/deactivate settings, not hard delete.
    """

    message: str = Field(default="Company settings deactivated successfully")
    company_id: str


CompanySettingsDeactivatedResponse = CompanySettingsDeletedResponse