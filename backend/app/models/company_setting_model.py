"""
Company Settings model for HR system configuration.

Stores global HR configuration including:
- General company information
- Work week configuration
- Leave policy defaults
- Payroll settings
- Claim policy defaults
- System-wide HR settings

Pattern:
- Single active document per company for now
- Can be extended to multi-tenant later using company_id
- Updated by Admin only through API
- Read by services for business rules

Important:
- This model stores global company-level rules only.
- Employee-specific data should not be stored here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


VALID_WEEKDAYS = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}


class WorkWeekConfig(BaseModel):
    """
    Work week configuration.

    Defines working days, weekend days, standard work hours,
    and optional half-day rules.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
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
        """
        Validate weekday list and remove duplicates.
        """
        if not value:
            raise ValueError("Day list cannot be empty")

        normalized: list[str] = []

        for day in value:
            item = str(day).strip().lower()

            if item not in VALID_WEEKDAYS:
                raise ValueError(
                    f"Invalid day: {day}. Must be one of: {', '.join(sorted(VALID_WEEKDAYS))}"
                )

            if item not in normalized:
                normalized.append(item)

        return normalized

    @field_validator("half_day_on")
    @classmethod
    def validate_half_day(cls, value: Optional[str]) -> Optional[str]:
        """
        Validate optional half-day.
        """
        if value is None:
            return None

        value = str(value).strip().lower()

        if not value:
            return None

        if value not in VALID_WEEKDAYS:
            raise ValueError(
                f"Invalid half_day_on: {value}. Must be one of: {', '.join(sorted(VALID_WEEKDAYS))}"
            )

        return value

    @model_validator(mode="after")
    def validate_work_week_rules(self):
        """
        Validate work week consistency.
        """
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


class LeavePolicyConfig(BaseModel):
    """
    Global leave policy configuration.

    These are company-wide defaults.
    Specific leave types can override these rules later.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    leave_year_start_month: int = Field(
        default=1,
        ge=1,
        le=12,
        description="Month when leave year starts. 1 means January, 4 means April",
    )

    max_carryforward_days: int = Field(
        default=10,
        ge=0,
        le=365,
        description="Maximum leave days that can be carried forward",
    )

    carryforward_expiry_months: int = Field(
        default=3,
        ge=0,
        le=24,
        description="Months after which carried-forward leaves expire",
    )

    allow_leave_encashment: bool = Field(
        default=True,
        description="Whether employees can encash unused leaves",
    )

    min_encashment_days: int = Field(
        default=5,
        ge=0,
        description="Minimum leave balance required for encashment",
    )

    max_encashment_days: int = Field(
        default=30,
        ge=0,
        description="Maximum leave days that can be encashed per year",
    )

    probation_period_days: int = Field(
        default=90,
        ge=0,
        le=730,
        description="Standard probation period in days",
    )

    allow_leave_during_probation: bool = Field(
        default=True,
        description="Whether employees can take leave during probation",
    )

    probation_leave_limit_days: int = Field(
        default=3,
        ge=0,
        description="Maximum leave days during probation if allowed",
    )

    min_notice_days: int = Field(
        default=1,
        ge=0,
        description="Minimum advance notice for leave application",
    )

    max_advance_days: int = Field(
        default=90,
        ge=1,
        le=730,
        description="Maximum days in advance leave can be applied",
    )

    allow_backdated_leave: bool = Field(
        default=False,
        description="Whether employees can apply for backdated leave",
    )

    backdated_leave_days_limit: int = Field(
        default=7,
        ge=0,
        le=365,
        description="How many days back leave can be applied if allowed",
    )

    allow_half_day_leave: bool = Field(
        default=True,
        description="Whether half-day leave is allowed",
    )

    half_day_deduction: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Leave deduction for half-day leave",
    )

    allow_negative_balance: bool = Field(
        default=False,
        description="Whether negative leave balance is allowed",
    )

    max_negative_balance_days: int = Field(
        default=0,
        ge=0,
        le=365,
        description="Maximum negative leave balance allowed if enabled",
    )

    @model_validator(mode="after")
    def validate_leave_policy_rules(self):
        """
        Validate leave policy consistency.
        """
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


class PayrollConfig(BaseModel):
    """
    Payroll configuration.

    Defines pay cycle, currency, statutory deductions, and financial year.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    pay_cycle: str = Field(
        default="monthly",
        description="Pay cycle: monthly, bi-weekly, weekly",
    )

    pay_day: int = Field(
        default=1,
        ge=1,
        le=31,
        description="Day of month for salary payment when pay_cycle is monthly",
    )

    financial_year_start_month: int = Field(
        default=4,
        ge=1,
        le=12,
        description="Financial year start month. For India usually 4 for April",
    )

    currency: str = Field(
        default="INR",
        min_length=3,
        max_length=3,
        description="Company currency ISO code",
    )

    enable_tds: bool = Field(
        default=True,
        description="Whether TDS is enabled",
    )

    enable_pf: bool = Field(
        default=True,
        description="Whether Provident Fund is enabled",
    )

    pf_rate_employee: float = Field(
        default=12.0,
        ge=0.0,
        le=100.0,
        description="Employee PF contribution percentage",
    )

    pf_rate_employer: float = Field(
        default=12.0,
        ge=0.0,
        le=100.0,
        description="Employer PF contribution percentage",
    )

    enable_esi: bool = Field(
        default=False,
        description="Whether ESI is enabled",
    )

    esi_rate_employee: float = Field(
        default=0.75,
        ge=0.0,
        le=100.0,
        description="Employee ESI contribution percentage",
    )

    esi_rate_employer: float = Field(
        default=3.25,
        ge=0.0,
        le=100.0,
        description="Employer ESI contribution percentage",
    )

    enable_professional_tax: bool = Field(
        default=True,
        description="Whether professional tax is enabled",
    )

    professional_tax_state: Optional[str] = Field(
        default=None,
        max_length=50,
        description="State for professional tax",
    )

    @field_validator("pay_cycle")
    @classmethod
    def validate_pay_cycle(cls, value: str) -> str:
        """
        Validate pay cycle.
        """
        value = str(value).strip().lower()
        allowed_cycles = {"monthly", "bi-weekly", "weekly"}

        if value not in allowed_cycles:
            raise ValueError(
                f"pay_cycle must be one of: {', '.join(sorted(allowed_cycles))}"
            )

        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        """
        Normalize and validate currency code.
        """
        value = str(value).strip().upper()

        if not value.isalpha() or len(value) != 3:
            raise ValueError("currency must be a valid 3-letter code, for example INR")

        return value

    @field_validator("professional_tax_state")
    @classmethod
    def normalize_professional_tax_state(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        """
        Normalize professional tax state.
        """
        if value is None:
            return None

        value = str(value).strip()
        return value or None

    @model_validator(mode="after")
    def validate_payroll_rules(self):
        """
        Validate payroll consistency.
        """
        if self.pay_cycle != "monthly" and self.pay_day != 1:
            raise ValueError(
                "pay_day should be 1 when pay_cycle is weekly or bi-weekly"
            )

        if not self.enable_pf:
            if self.pf_rate_employee != 0 or self.pf_rate_employer != 0:
                raise ValueError(
                    "PF rates must be 0 when enable_pf=False"
                )

        if not self.enable_esi:
            if self.esi_rate_employee != 0 or self.esi_rate_employer != 0:
                raise ValueError(
                    "ESI rates must be 0 when enable_esi=False"
                )

        if self.enable_professional_tax and not self.professional_tax_state:
            raise ValueError(
                "professional_tax_state is required when enable_professional_tax=True"
            )

        if not self.enable_professional_tax and self.professional_tax_state is not None:
            raise ValueError(
                "professional_tax_state must be None when enable_professional_tax=False"
            )

        return self


class ClaimPolicyConfig(BaseModel):
    """
    Global claim policy configuration.

    These are company-wide defaults.
    Specific claim types can override these rules later.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    require_bill_above: float = Field(
        default=500.0,
        ge=0.0,
        description="Amount above which bill is mandatory",
    )

    max_bill_file_size_mb: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum file size for bill upload in MB",
    )

    allowed_bill_formats: list[str] = Field(
        default_factory=lambda: ["pdf", "jpg", "jpeg", "png"],
        description="Allowed file formats for bills",
    )

    enable_manager_approval: bool = Field(
        default=True,
        description="Whether manager approval is required",
    )

    manager_approval_threshold: float = Field(
        default=5000.0,
        ge=0.0,
        description="Amount above which manager approval is required",
    )

    enable_finance_approval: bool = Field(
        default=True,
        description="Whether finance approval is required",
    )

    finance_approval_threshold: float = Field(
        default=20000.0,
        ge=0.0,
        description="Amount above which finance approval is required",
    )

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

    claim_submission_deadline_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Days within which claim must be submitted after expense date",
    )

    allow_advance_claim: bool = Field(
        default=False,
        description="Whether claims can be submitted before expense date",
    )

    reimbursement_processing_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="Standard days to process approved claims",
    )

    @field_validator("allowed_bill_formats")
    @classmethod
    def validate_allowed_bill_formats(cls, value: list[str]) -> list[str]:
        """
        Normalize allowed bill formats.
        """
        if not value:
            raise ValueError("allowed_bill_formats cannot be empty")

        cleaned: list[str] = []

        for item in value:
            extension = str(item).strip().lower().replace(".", "")

            if not extension:
                continue

            if not extension.isalnum():
                raise ValueError("allowed_bill_formats can contain only file extensions")

            if extension not in cleaned:
                cleaned.append(extension)

        if not cleaned:
            raise ValueError("allowed_bill_formats cannot be empty")

        return cleaned

    @model_validator(mode="after")
    def validate_claim_policy_rules(self):
        """
        Validate claim policy consistency.
        """
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


class CompanyInfo(BaseModel):
    """
    General company information.

    Used for reports, salary slips, documents, and compliance.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    company_name: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Legal company name",
    )

    company_short_name: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Short or trade name",
    )

    email: EmailStr = Field(
        ...,
        description="Company email address",
    )

    phone: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Company phone number",
    )

    website: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Company website URL",
    )

    address_line1: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Address line 1",
    )

    address_line2: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Address line 2",
    )

    city: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="City",
    )

    state: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="State or province",
    )

    pincode: str = Field(
        ...,
        min_length=2,
        max_length=20,
        description="Postal or ZIP code",
    )

    country: str = Field(
        default="India",
        min_length=2,
        max_length=100,
        description="Country",
    )

    pan: Optional[str] = Field(
        default=None,
        max_length=20,
        description="PAN number",
    )

    tan: Optional[str] = Field(
        default=None,
        max_length=20,
        description="TAN number",
    )

    gstin: Optional[str] = Field(
        default=None,
        max_length=20,
        description="GSTIN number",
    )

    pf_registration_number: Optional[str] = Field(
        default=None,
        max_length=50,
        description="PF registration number",
    )

    esi_registration_number: Optional[str] = Field(
        default=None,
        max_length=50,
        description="ESI registration number",
    )

    industry: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Industry or sector",
    )

    company_size: Optional[str] = Field(
        default=None,
        description="Company size: startup, small, medium, large, enterprise",
    )

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
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        """
        Strip optional text fields.
        """
        if value is None:
            return None

        value = str(value).strip()
        return value or None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        """
        Basic phone validation.

        Keeps +, digits, spaces, and hyphen.
        """
        if value is None:
            return None

        allowed_chars = set("+0123456789 -")

        if any(char not in allowed_chars for char in value):
            raise ValueError("phone can contain only digits, spaces, +, and -")

        return value

    @field_validator("pan", "tan", "gstin")
    @classmethod
    def normalize_tax_ids(cls, value: Optional[str]) -> Optional[str]:
        """
        Normalize tax IDs to uppercase.
        """
        if value is None:
            return None

        value = str(value).strip().upper()
        return value or None

    @field_validator("company_size")
    @classmethod
    def validate_company_size(cls, value: Optional[str]) -> Optional[str]:
        """
        Validate company size.
        """
        if value is None:
            return None

        value = str(value).strip().lower()

        if not value:
            return None

        allowed_sizes = {"startup", "small", "medium", "large", "enterprise"}

        if value not in allowed_sizes:
            raise ValueError(
                f"company_size must be one of: {', '.join(sorted(allowed_sizes))}"
            )

        return value


class SystemConfig(BaseModel):
    """
    General system-level HR configuration.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    timezone: str = Field(
        default="Asia/Kolkata",
        min_length=3,
        max_length=100,
        description="Default company timezone",
    )

    locale: str = Field(
        default="en-IN",
        min_length=2,
        max_length=20,
        description="Default locale",
    )

    default_country: str = Field(
        default="India",
        min_length=2,
        max_length=100,
        description="Default country",
    )

    default_location: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Default office location or branch",
    )

    allow_employee_self_service: bool = Field(
        default=True,
        description="Whether employee self-service is enabled",
    )

    allow_ai_assistant: bool = Field(
        default=True,
        description="Whether HR AI assistant is enabled",
    )

    @field_validator("timezone", "locale", "default_country", "default_location")
    @classmethod
    def normalize_text(cls, value: Optional[str]) -> Optional[str]:
        """
        Normalize text values.
        """
        if value is None:
            return None

        value = str(value).strip()
        return value or None


class CompanySettings(BaseModel):
    """
    Main company settings model.

    Single document that contains all global HR configuration.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    company_id: str = Field(
        default="default",
        min_length=2,
        max_length=100,
        description="Company identifier for future multi-tenant support",
    )

    company_info: CompanyInfo = Field(
        ...,
        description="General company information",
    )

    system: SystemConfig = Field(
        default_factory=SystemConfig,
        description="System-level HR configuration",
    )

    work_week: WorkWeekConfig = Field(
        default_factory=WorkWeekConfig,
        description="Work week configuration",
    )

    leave_policy: LeavePolicyConfig = Field(
        default_factory=LeavePolicyConfig,
        description="Leave policy configuration",
    )

    payroll: PayrollConfig = Field(
        default_factory=PayrollConfig,
        description="Payroll configuration",
    )

    claim_policy: ClaimPolicyConfig = Field(
        default_factory=ClaimPolicyConfig,
        description="Claim policy configuration",
    )

    is_active: bool = Field(
        default=True,
        description="Whether these settings are active",
    )

    created_by: Optional[str] = Field(
        default=None,
        description="User ID who created these settings",
    )

    updated_by: Optional[str] = Field(
        default=None,
        description="User ID who last updated these settings",
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Creation timestamp",
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp",
    )

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: str) -> str:
        """
        Normalize company ID.
        """
        value = str(value).strip().lower()

        if not value:
            raise ValueError("company_id cannot be empty")

        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "company_id can contain only letters, numbers, hyphen, and underscore"
            )

        return value

    @field_validator("created_by", "updated_by")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        """
        Strip optional audit fields.
        """
        if value is None:
            return None

        value = str(value).strip()
        return value or None


class CompanySettingsInDB(CompanySettings):
    """
    Company settings as stored in MongoDB with _id field.

    Used internally by repositories.
    """

    id: Optional[str] = Field(default=None, alias="_id")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class CompanySettingsResponse(BaseModel):
    """
    Safe company settings response for API output.

    Used by frontend and services to read configuration.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str

    company_info: CompanyInfo
    system: SystemConfig
    work_week: WorkWeekConfig
    leave_policy: LeavePolicyConfig
    payroll: PayrollConfig
    claim_policy: ClaimPolicyConfig

    is_active: bool

    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    created_at: datetime
    updated_at: datetime


class CompanySettingsSummary(BaseModel):
    """
    Lightweight summary for quick reference.

    Used when only basic configuration information is needed.
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


class CompanySettingsStatusResponse(BaseModel):
    """
    Simple response after activating/deactivating or updating company settings.
    """

    message: str
    company_id: str
    is_active: bool