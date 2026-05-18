"""
Holiday master data model.

Stores company holiday calendar with different holiday types.

Holiday calendar is used for:
- Leave working day calculation
- Payroll working day calculation
- AI explaining company holidays to employees

Pattern:
- HR/Admin can create/update holidays through API
- All authenticated users can read holidays for calendar display
- Holidays can be location-specific
- Soft delete with is_active flag
"""

from datetime import date as Date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HolidayType(str, Enum):
    """
    Supported holiday types.

    Keep values lowercase because these values will be stored in MongoDB.
    """

    NATIONAL = "national"
    FESTIVAL = "festival"
    COMPANY = "company"
    OPTIONAL = "optional"
    REGIONAL = "regional"


class Holiday(BaseModel):
    """
    Holiday document model for the holidays collection.

    Represents company holidays like:
    - National holidays, for example Independence Day, Republic Day
    - Festival holidays, for example Diwali, Holi, Eid
    - Company-specific holidays, for example Founder's Day
    - Optional holidays that employees can choose
    - Regional holidays for specific locations/states
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True,
    )

    # -------------------------
    # Basic holiday details
    # -------------------------

    date: Date = Field(
        ...,
        description="Holiday date",
    )

    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Holiday name, for example Independence Day, Holi, Diwali",
    )

    type: HolidayType = Field(
        default=HolidayType.NATIONAL,
        description="Holiday type: national, festival, company, optional, regional",
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Holiday description or significance",
    )

    # -------------------------
    # Working day rules
    # -------------------------

    is_working_day: bool = Field(
        default=False,
        description=(
            "Whether this date is still treated as a working day. "
            "For normal holidays this should be False. "
            "For half-day holidays this should usually be True."
        ),
    )

    is_half_day: bool = Field(
        default=False,
        description="Whether this is a half-day holiday",
    )

    # -------------------------
    # Location and year
    # -------------------------

    location: Optional[str] = Field(
        default=None,
        max_length=100,
        description=(
            "Location or region this holiday applies to. "
            "Use None or 'All' for company-wide holidays. "
            "Examples: Noida, Mumbai, Bangalore, Delhi, Maharashtra"
        ),
    )

    year: Optional[int] = Field(
        default=None,
        ge=2020,
        le=2100,
        description=(
            "Year this holiday belongs to. "
            "If not provided, it is automatically derived from date.year."
        ),
    )

    # -------------------------
    # Optional holiday rules
    # -------------------------

    is_optional: bool = Field(
        default=False,
        description=(
            "Whether this is an optional holiday that employees can choose to take. "
            "Optional holidays usually have a yearly limit per employee."
        ),
    )

    optional_limit_per_employee: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "If this is an optional holiday, this defines how many optional holidays "
            "each employee can take per year."
        ),
    )

    # -------------------------
    # Display and status
    # -------------------------

    display_order: int = Field(
        default=0,
        ge=0,
        description="Used to sort holidays in frontend calendar",
    )

    is_active: bool = Field(
        default=True,
        description="Soft delete flag. Inactive holidays are hidden from calendar",
    )

    # -------------------------
    # Audit fields
    # -------------------------

    created_by: Optional[str] = Field(
        default=None,
        description="User ID or employee ID of the HR/Admin who created this holiday",
    )

    updated_by: Optional[str] = Field(
        default=None,
        description="User ID or employee ID of the HR/Admin who last updated this holiday",
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

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """
        Normalize holiday name.

        Do not force title case because names like Eid-ul-Fitr,
        Dr. Ambedkar Jayanti, or Company Offsite Day should keep formatting.
        """
        value = value.strip()

        if not value:
            raise ValueError("Holiday name cannot be empty")

        return value

    @field_validator("type", mode="before")
    @classmethod
    def validate_type(cls, value: str) -> str:
        """
        Normalize and validate holiday type.
        """
        if isinstance(value, HolidayType):
            return value.value

        value = str(value).strip().lower()

        allowed_types = {item.value for item in HolidayType}

        if value not in allowed_types:
            raise ValueError(
                f"Holiday type must be one of: {', '.join(sorted(allowed_types))}"
            )

        return value

    @field_validator(
        "description",
        "location",
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

        value = str(value).strip()
        return value or None

    @field_validator("location")
    @classmethod
    def normalize_location(cls, value: Optional[str]) -> Optional[str]:
        """
        Normalize location value.

        Rules:
        - None means company-wide/all locations.
        - Empty string becomes None.
        - 'all' or 'ALL' becomes 'All'.
        - Other values keep readable formatting.
        """
        if value is None:
            return None

        value = str(value).strip()

        if not value:
            return None

        if value.lower() == "all":
            return "All"

        return value

    # -------------------------
    # Cross-field business validation
    # -------------------------

    @model_validator(mode="after")
    def validate_business_rules(self):
        """
        Validate rules that depend on multiple fields.
        """

        # Auto-fill year from date if not provided.
        if self.year is None:
            self.year = self.date.year

        # Year must always match the holiday date.
        if self.year != self.date.year:
            raise ValueError("year must match date.year")

        # A half-day holiday is still a partial working day.
        # So if is_half_day=True, is_working_day should also be True.
        if self.is_half_day and not self.is_working_day:
            raise ValueError(
                "is_half_day can only be True when is_working_day is also True"
            )

        # Keep type='optional' and is_optional=True consistent.
        if self.type == HolidayType.OPTIONAL.value:
            self.is_optional = True

        if self.is_optional and self.type != HolidayType.OPTIONAL.value:
            self.type = HolidayType.OPTIONAL.value

        # Optional holidays must have an employee yearly limit.
        if self.is_optional:
            if self.optional_limit_per_employee is None:
                raise ValueError(
                    "optional_limit_per_employee is required when is_optional=True"
                )

            if self.optional_limit_per_employee <= 0:
                raise ValueError(
                    "optional_limit_per_employee must be greater than 0 for optional holidays"
                )

        # Non-optional holidays should not store optional limit.
        if not self.is_optional and self.optional_limit_per_employee is not None:
            raise ValueError(
                "optional_limit_per_employee must be None when is_optional=False"
            )

        return self


class HolidayInDB(Holiday):
    """
    Holiday model as stored in MongoDB with _id field.

    Used internally by repositories.
    """

    id: Optional[str] = Field(default=None, alias="_id")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True,
    )


class HolidayResponse(BaseModel):
    """
    Safe holiday response for API output.

    Used by frontend calendar, leave application pages, employee dashboards,
    HR dashboards, and admin screens.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Holiday ID")

    date: Date
    name: str
    type: str
    description: Optional[str] = None

    is_working_day: bool
    is_half_day: bool

    location: Optional[str] = None
    year: int

    is_optional: bool
    optional_limit_per_employee: Optional[int] = None

    display_order: int = 0
    is_active: bool

    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    created_at: datetime
    updated_at: datetime


class HolidayListItem(BaseModel):
    """
    Lightweight holiday item for list view.

    Used by:
    - GET holidays list
    - HR/Admin holiday table
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    date: Date
    name: str
    type: str

    is_working_day: bool
    is_half_day: bool

    location: Optional[str] = None
    year: int

    is_optional: bool
    display_order: int = 0
    is_active: bool


class HolidayCalendarResponse(BaseModel):
    """
    Very lightweight holiday response for frontend calendar widget.

    Use this when employee leave form only needs to display holiday markers.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    date: Date
    name: str
    type: str

    is_working_day: bool
    is_half_day: bool
    is_optional: bool

    location: Optional[str] = None


class HolidayDropdownResponse(BaseModel):
    """
    Lightweight response for dropdowns or quick selectors.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    date: Date
    type: str
    location: Optional[str] = None
    is_optional: bool


class HolidayStatistics(BaseModel):
    """
    Statistics response for holiday dashboard.

    These values will be calculated in repository/service layer later.
    """

    total_holidays: int = Field(default=0, ge=0)

    active_holidays: int = Field(default=0, ge=0)
    inactive_holidays: int = Field(default=0, ge=0)

    national_holidays: int = Field(default=0, ge=0)
    festival_holidays: int = Field(default=0, ge=0)
    company_holidays: int = Field(default=0, ge=0)
    optional_holidays: int = Field(default=0, ge=0)
    regional_holidays: int = Field(default=0, ge=0)

    working_day_holidays: int = Field(default=0, ge=0)
    non_working_day_holidays: int = Field(default=0, ge=0)
    half_day_holidays: int = Field(default=0, ge=0)

    location_specific_holidays: int = Field(default=0, ge=0)
    company_wide_holidays: int = Field(default=0, ge=0)

    holidays_per_year: dict[int, int] = Field(
        default_factory=dict,
        description="Holiday count grouped by year",
    )

    holidays_per_location: dict[str, int] = Field(
        default_factory=dict,
        description="Holiday count grouped by location",
    )