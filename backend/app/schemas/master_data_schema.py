"""
Request and response schemas for master data APIs.

This file defines the API contract for master data modules.

Current scope:
- Departments
- Designations
- Leave Types
- Claim Types

Later scope:
- Company Settings
- Holiday Calendar

Important:
- Schemas are used by FastAPI routes.
- Models are used for MongoDB document structure.
- Do not put database logic here.
- Do not put business logic here.
"""

from datetime import date as Date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# -------------------------
# Shared validators/helpers
# -------------------------


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    """
    Strip optional text fields.

    Empty string becomes None so MongoDB does not store useless "" values.
    """
    if value is None:
        return None

    value = value.strip()
    return value or None


def validate_master_code(value: str, label: str = "Code") -> str:
    """
    Validate master data code.

    Rules:
    - Strip spaces
    - Convert to uppercase
    - Allow only letters, numbers, and underscores
    - No spaces
    - No hyphen
    - No special characters except underscore
    """
    value = value.strip().upper()

    if not value:
        raise ValueError(f"{label} cannot be empty")

    if not value.replace("_", "").isalnum():
        raise ValueError(
            f"{label} can only contain uppercase letters, numbers, and underscores"
        )

    return value


def normalize_gender_specific(value: Optional[str]) -> Optional[str]:
    """
    Normalize gender specific field.

    Allowed values:
    - male
    - female
    - None
    """
    if value is None:
        return None

    value = value.strip().lower()

    if not value:
        return None

    if value not in {"male", "female"}:
        raise ValueError("gender_specific must be 'male', 'female', or None")

    return value


def normalize_currency(value: Optional[str]) -> str:
    """
    Normalize currency code.

    Default currency is INR.
    """
    if value is None:
        return "INR"

    value = value.strip().upper()

    if not value:
        return "INR"

    if not value.isalpha() or len(value) != 3:
        raise ValueError("currency must be a valid 3-letter code, for example INR")

    return value


def normalize_file_types(value: Optional[list[str]]) -> list[str]:
    """
    Normalize allowed file extensions.

    Rules:
    - Lowercase
    - Remove leading dot
    - Remove duplicates
    """
    if not value:
        return ["pdf", "jpg", "jpeg", "png"]

    cleaned: list[str] = []

    for item in value:
        item = item.strip().lower().lstrip(".")

        if not item:
            continue

        if item not in cleaned:
            cleaned.append(item)

    if not cleaned:
        raise ValueError("allowed_file_types cannot be empty")

    return cleaned


# -------------------------
# Department Schemas
# -------------------------


class CreateDepartmentRequest(BaseModel):
    """
    Request schema for creating a new department.

    Used by:
        POST /api/v1/master-data/departments

    Required role:
        HR or Admin
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Department name",
        examples=["Engineering", "Human Resources", "AI/ML Team"],
    )

    code: str = Field(
        ...,
        min_length=2,
        max_length=20,
        description="Unique department code",
        examples=["ENG", "HR", "AI_ML"],
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Department description and responsibilities",
    )

    head_id: Optional[str] = Field(
        default=None,
        description="Employee/User ID of department head. Later this should reference employees collection.",
    )

    parent_id: Optional[str] = Field(
        default=None,
        description="Parent department ID for nested department structure",
    )

    location: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Department location or branch",
        examples=["Noida", "Mumbai", "Remote"],
    )

    display_order: int = Field(
        default=0,
        ge=0,
        description="Sort order in frontend dropdowns",
    )

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        return validate_master_code(value, label="Department code")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Department name cannot be empty")

        return value

    @field_validator("description", "head_id", "parent_id", "location")
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class UpdateDepartmentRequest(BaseModel):
    """
    Request schema for updating an existing department.

    Used by:
        PATCH /api/v1/master-data/departments/{department_id}

    Required role:
        HR or Admin
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    name: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=100,
        description="Updated department name",
    )

    code: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=20,
        description="Updated department code",
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Updated department description",
    )

    head_id: Optional[str] = Field(
        default=None,
        description="Updated department head employee/user ID",
    )

    parent_id: Optional[str] = Field(
        default=None,
        description="Updated parent department ID",
    )

    location: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Updated location or branch",
    )

    display_order: Optional[int] = Field(
        default=None,
        ge=0,
        description="Updated sort order",
    )

    is_active: Optional[bool] = Field(
        default=None,
        description="Activate or deactivate department",
    )

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        return validate_master_code(value, label="Department code")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("Department name cannot be empty")

        return value

    @field_validator("description", "head_id", "parent_id", "location")
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class DepartmentListResponse(BaseModel):
    """
    Response schema for department list view.

    Used by:
        GET /api/v1/master-data/departments
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    description: Optional[str] = None
    head_id: Optional[str] = None
    parent_id: Optional[str] = None
    location: Optional[str] = None
    display_order: int = 0
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DepartmentDetailResponse(DepartmentListResponse):
    """
    Response schema for a single department detail view.

    Used by:
        GET /api/v1/master-data/departments/{department_id}
    """

    head_name: Optional[str] = Field(
        default=None,
        description="Name of department head if head_id is set",
    )

    head_email: Optional[str] = Field(
        default=None,
        description="Email of department head if head_id is set",
    )

    parent_name: Optional[str] = Field(
        default=None,
        description="Name of parent department if parent_id is set",
    )

    employee_count: int = Field(
        default=0,
        ge=0,
        description="Number of active employees in this department",
    )

    children_count: int = Field(
        default=0,
        ge=0,
        description="Number of active child departments",
    )


class DepartmentDropdownResponse(BaseModel):
    """
    Lightweight department response for frontend dropdowns.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    location: Optional[str] = None
    is_active: bool


class DepartmentCreatedResponse(BaseModel):
    """
    Response schema after creating a department.

    Used by:
        POST /api/v1/master-data/departments
    """

    message: str = Field(default="Department created successfully")
    department_id: str
    department: DepartmentListResponse


class DepartmentUpdatedResponse(BaseModel):
    """
    Response schema after updating a department.

    Used by:
        PATCH /api/v1/master-data/departments/{department_id}
    """

    message: str = Field(default="Department updated successfully")
    department: DepartmentListResponse


class DepartmentDeactivatedResponse(BaseModel):
    """
    Response schema after deactivating a department.

    Used by:
        DELETE /api/v1/master-data/departments/{department_id}
    """

    message: str = Field(default="Department deactivated successfully")
    department_id: str


DepartmentDeletedResponse = DepartmentDeactivatedResponse


class BulkDepartmentImportRequest(BaseModel):
    """
    Request schema for bulk importing departments.

    Used by:
        POST /api/v1/master-data/departments/bulk-import

    Required role:
        Admin only
    """

    model_config = ConfigDict(extra="forbid")

    departments: list[CreateDepartmentRequest] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of departments to create",
    )

    skip_duplicates: bool = Field(
        default=True,
        description="Skip departments with duplicate codes instead of failing the full import",
    )


class BulkDepartmentImportResponse(BaseModel):
    """
    Response schema for bulk department import operation.
    """

    message: str
    created_count: int = Field(..., ge=0)
    skipped_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    created_ids: list[str] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)


class DepartmentListQuery(BaseModel):
    """
    Query parameters for listing departments.

    Used by:
        GET /api/v1/master-data/departments
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    is_active: Optional[bool] = Field(default=None)
    location: Optional[str] = Field(default=None)
    parent_id: Optional[str] = Field(default=None)
    search: Optional[str] = Field(default=None, min_length=2, max_length=100)

    sort_by: Literal["display_order", "name", "code", "created_at", "updated_at"] = Field(
        default="display_order"
    )

    sort_order: Literal["asc", "desc"] = Field(default="asc")

    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("location", "parent_id", "search")
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


# -------------------------
# Designation Schemas
# -------------------------


class CreateDesignationRequest(BaseModel):
    """
    Request schema for creating a new designation.

    Used by:
        POST /api/v1/master-data/designations

    Required role:
        HR or Admin
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Designation name",
        examples=["Software Engineer", "HR Manager", "Data Scientist"],
    )

    code: str = Field(
        ...,
        min_length=2,
        max_length=20,
        description="Unique designation code",
        examples=["SWE", "HRM", "DS", "TL", "AI_ENG"],
    )

    level: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Career level, for example 1=Junior, 2=Mid, 3=Senior, 4=Lead, 5=Principal",
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Designation description and responsibilities",
    )

    department_id: Optional[str] = Field(
        default=None,
        description="Optional department ID if designation is department-specific",
    )

    display_order: int = Field(
        default=0,
        ge=0,
        description="Sort order in frontend dropdowns",
    )

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        return validate_master_code(value, label="Designation code")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Designation name cannot be empty")

        return value

    @field_validator("description", "department_id")
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class UpdateDesignationRequest(BaseModel):
    """
    Request schema for updating an existing designation.

    Used by:
        PATCH /api/v1/master-data/designations/{designation_id}

    Required role:
        HR or Admin
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    code: Optional[str] = Field(default=None, min_length=2, max_length=20)
    level: Optional[int] = Field(default=None, ge=1, le=10)
    description: Optional[str] = Field(default=None, max_length=500)
    department_id: Optional[str] = Field(default=None)
    display_order: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = Field(default=None)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        return validate_master_code(value, label="Designation code")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("Designation name cannot be empty")

        return value

    @field_validator("description", "department_id")
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class DesignationListResponse(BaseModel):
    """
    Response schema for designation list view.

    Used by:
        GET /api/v1/master-data/designations
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    level: Optional[int] = None
    description: Optional[str] = None
    department_id: Optional[str] = None
    display_order: int = 0
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DesignationDetailResponse(DesignationListResponse):
    """
    Response schema for a single designation detail view.

    Used by:
        GET /api/v1/master-data/designations/{designation_id}
    """

    department_name: Optional[str] = Field(default=None)
    department_code: Optional[str] = Field(default=None)
    employee_count: int = Field(default=0, ge=0)


class DesignationDropdownResponse(BaseModel):
    """
    Lightweight designation response for frontend dropdowns.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    level: Optional[int] = None
    department_id: Optional[str] = None
    is_active: bool


class DesignationCreatedResponse(BaseModel):
    """
    Response schema after creating a designation.

    Used by:
        POST /api/v1/master-data/designations
    """

    message: str = Field(default="Designation created successfully")
    designation_id: str
    designation: DesignationListResponse


class DesignationUpdatedResponse(BaseModel):
    """
    Response schema after updating a designation.

    Used by:
        PATCH /api/v1/master-data/designations/{designation_id}
    """

    message: str = Field(default="Designation updated successfully")
    designation: DesignationListResponse


class DesignationDeactivatedResponse(BaseModel):
    """
    Response schema after deactivating a designation.

    Used by:
        DELETE /api/v1/master-data/designations/{designation_id}
    """

    message: str = Field(default="Designation deactivated successfully")
    designation_id: str


DesignationDeletedResponse = DesignationDeactivatedResponse


class BulkDesignationImportRequest(BaseModel):
    """
    Request schema for bulk importing designations.

    Used by:
        POST /api/v1/master-data/designations/bulk-import

    Required role:
        Admin only
    """

    model_config = ConfigDict(extra="forbid")

    designations: list[CreateDesignationRequest] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of designations to create",
    )

    skip_duplicates: bool = Field(
        default=True,
        description="Skip designations with duplicate codes instead of failing the full import",
    )


class BulkDesignationImportResponse(BaseModel):
    """
    Response schema for bulk designation import operation.
    """

    message: str
    created_count: int = Field(..., ge=0)
    skipped_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    created_ids: list[str] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)


class DesignationListQuery(BaseModel):
    """
    Query parameters for listing designations.

    Used by:
        GET /api/v1/master-data/designations
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    is_active: Optional[bool] = Field(default=None)
    department_id: Optional[str] = Field(default=None)
    level: Optional[int] = Field(default=None, ge=1, le=10)
    search: Optional[str] = Field(default=None, min_length=2, max_length=100)

    sort_by: Literal[
        "display_order",
        "name",
        "code",
        "level",
        "created_at",
        "updated_at",
    ] = Field(default="display_order")

    sort_order: Literal["asc", "desc"] = Field(default="asc")
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("department_id", "search")
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


# -------------------------
# Leave Type Schemas
# -------------------------


class CreateLeaveTypeRequest(BaseModel):
    """
    Request schema for creating a new leave type.

    Used by:
        POST /api/v1/master-data/leave-types

    Required role:
        HR or Admin
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Leave type name",
        examples=["Sick Leave", "Casual Leave", "Earned Leave"],
    )

    code: str = Field(
        ...,
        min_length=2,
        max_length=20,
        description="Unique leave type code",
        examples=["SICK", "CASUAL", "EARNED"],
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Leave type description and usage guidelines",
    )

    default_annual_grant: int = Field(
        ...,
        ge=0,
        description="Default number of days granted per year",
        examples=[12],
    )

    max_annual_limit: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum days allowed per year",
    )

    requires_approval: bool = Field(
        default=True,
        description="Whether leave requires approval",
    )

    requires_documentation: bool = Field(
        default=False,
        description="Whether supporting document is required",
    )

    documentation_threshold_days: Optional[int] = Field(
        default=None,
        ge=1,
        description="Documentation required after this many days",
    )

    min_notice_days: int = Field(
        default=0,
        ge=0,
        description="Minimum advance notice required in days",
    )

    max_consecutive_days: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum consecutive days allowed",
    )

    carry_forward_allowed: bool = Field(
        default=False,
        description="Whether unused leave can be carried forward",
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
        description="Months after which carried-forward leave expires",
    )

    is_paid: bool = Field(
        default=True,
        description="Whether this leave type is paid",
    )

    encashment_allowed: bool = Field(
        default=False,
        description="Whether unused leave can be encashed",
    )

    max_encashment_days: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum days allowed for encashment",
    )

    is_accrued: bool = Field(
        default=False,
        description="Whether leave is accrued monthly",
    )

    accrual_rate_per_month: Optional[float] = Field(
        default=None,
        ge=0,
        description="Monthly accrual rate if is_accrued=True",
    )

    gender_specific: Optional[str] = Field(
        default=None,
        description="Gender restriction: male, female, or None",
    )

    available_during_probation: bool = Field(
        default=True,
        description="Whether leave is available during probation",
    )

    probation_grant_percentage: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        description="Percentage available during probation",
    )

    display_order: int = Field(
        default=0,
        ge=0,
        description="Sort order in frontend dropdowns",
    )

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        return validate_master_code(value, label="Leave type code")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Leave type name cannot be empty")

        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("gender_specific")
    @classmethod
    def validate_gender_specific(cls, value: Optional[str]) -> Optional[str]:
        return normalize_gender_specific(value)

    @model_validator(mode="after")
    def validate_leave_type_rules(self):
        """
        Validate fields that depend on each other.
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


class UpdateLeaveTypeRequest(BaseModel):
    """
    Request schema for updating an existing leave type.

    Used by:
        PATCH /api/v1/master-data/leave-types/{leave_type_id}

    Required role:
        HR or Admin

    Notes:
    - All fields are optional.
    - Only provided fields should be updated.
    - Full business consistency should also be checked in service layer after merging existing + update data.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    code: Optional[str] = Field(default=None, min_length=2, max_length=20)
    description: Optional[str] = Field(default=None, max_length=500)

    default_annual_grant: Optional[int] = Field(default=None, ge=0)
    max_annual_limit: Optional[int] = Field(default=None, ge=0)

    requires_approval: Optional[bool] = Field(default=None)
    requires_documentation: Optional[bool] = Field(default=None)
    documentation_threshold_days: Optional[int] = Field(default=None, ge=1)

    min_notice_days: Optional[int] = Field(default=None, ge=0)
    max_consecutive_days: Optional[int] = Field(default=None, ge=1)

    carry_forward_allowed: Optional[bool] = Field(default=None)
    max_carry_forward_days: Optional[int] = Field(default=None, ge=0)
    carry_forward_expiry_months: Optional[int] = Field(default=None, ge=1, le=12)

    is_paid: Optional[bool] = Field(default=None)
    encashment_allowed: Optional[bool] = Field(default=None)
    max_encashment_days: Optional[int] = Field(default=None, ge=0)

    is_accrued: Optional[bool] = Field(default=None)
    accrual_rate_per_month: Optional[float] = Field(default=None, ge=0)

    gender_specific: Optional[str] = Field(default=None)

    available_during_probation: Optional[bool] = Field(default=None)
    probation_grant_percentage: Optional[int] = Field(default=None, ge=0, le=100)

    display_order: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = Field(default=None)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        return validate_master_code(value, label="Leave type code")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("Leave type name cannot be empty")

        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("gender_specific")
    @classmethod
    def validate_gender_specific(cls, value: Optional[str]) -> Optional[str]:
        return normalize_gender_specific(value)


class LeaveTypeListResponse(BaseModel):
    """
    Response schema for leave type list view.

    Used by:
        GET /api/v1/master-data/leave-types
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
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

    display_order: int = 0
    is_active: bool

    created_at: datetime
    updated_at: datetime


class LeaveTypeDetailResponse(LeaveTypeListResponse):
    """
    Response schema for a single leave type detail view.

    Used by:
        GET /api/v1/master-data/leave-types/{leave_type_id}
    """

    total_employees_granted: int = Field(default=0, ge=0)
    total_applications_this_year: int = Field(default=0, ge=0)


class LeaveTypeDropdownResponse(BaseModel):
    """
    Lightweight leave type response for frontend dropdowns.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    default_annual_grant: int
    min_notice_days: int
    requires_documentation: bool
    documentation_threshold_days: Optional[int] = None
    is_paid: bool
    gender_specific: Optional[str] = None
    is_active: bool


class LeaveTypeCreatedResponse(BaseModel):
    """
    Response schema after creating a leave type.

    Used by:
        POST /api/v1/master-data/leave-types
    """

    message: str = Field(default="Leave type created successfully")
    leave_type_id: str
    leave_type: LeaveTypeListResponse


class LeaveTypeUpdatedResponse(BaseModel):
    """
    Response schema after updating a leave type.

    Used by:
        PATCH /api/v1/master-data/leave-types/{leave_type_id}
    """

    message: str = Field(default="Leave type updated successfully")
    leave_type: LeaveTypeListResponse


class LeaveTypeDeactivatedResponse(BaseModel):
    """
    Response schema after deactivating a leave type.

    Used by:
        DELETE /api/v1/master-data/leave-types/{leave_type_id}
    """

    message: str = Field(default="Leave type deactivated successfully")
    leave_type_id: str


LeaveTypeDeletedResponse = LeaveTypeDeactivatedResponse


class BulkLeaveTypeImportRequest(BaseModel):
    """
    Request schema for bulk importing leave types.

    Used by:
        POST /api/v1/master-data/leave-types/bulk-import

    Required role:
        Admin only
    """

    model_config = ConfigDict(extra="forbid")

    leave_types: list[CreateLeaveTypeRequest] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of leave types to create",
    )

    skip_duplicates: bool = Field(
        default=True,
        description="Skip leave types with duplicate codes instead of failing the full import",
    )


class BulkLeaveTypeImportResponse(BaseModel):
    """
    Response schema for bulk leave type import operation.
    """

    message: str
    created_count: int = Field(..., ge=0)
    skipped_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    created_ids: list[str] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)


class LeaveTypeListQuery(BaseModel):
    """
    Query parameters for listing leave types.

    Used by:
        GET /api/v1/master-data/leave-types
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    is_active: Optional[bool] = Field(default=None)
    is_paid: Optional[bool] = Field(default=None)
    requires_approval: Optional[bool] = Field(default=None)
    requires_documentation: Optional[bool] = Field(default=None)
    carry_forward_allowed: Optional[bool] = Field(default=None)
    encashment_allowed: Optional[bool] = Field(default=None)
    is_accrued: Optional[bool] = Field(default=None)
    available_during_probation: Optional[bool] = Field(default=None)
    gender_specific: Optional[str] = Field(default=None)

    search: Optional[str] = Field(default=None, min_length=2, max_length=100)

    sort_by: Literal[
        "display_order",
        "name",
        "code",
        "default_annual_grant",
        "max_annual_limit",
        "min_notice_days",
        "is_paid",
        "requires_approval",
        "requires_documentation",
        "carry_forward_allowed",
        "encashment_allowed",
        "is_accrued",
        "created_at",
        "updated_at",
    ] = Field(default="display_order")

    sort_order: Literal["asc", "desc"] = Field(default="asc")
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("gender_specific")
    @classmethod
    def validate_gender_specific(cls, value: Optional[str]) -> Optional[str]:
        return normalize_gender_specific(value)

    @field_validator("search")
    @classmethod
    def clean_search(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class LeaveTypeStatisticsResponse(BaseModel):
    """
    Statistics response for leave type dashboard.

    Used by:
        GET /api/v1/master-data/leave-types/statistics
    """

    total: int = Field(default=0, ge=0)
    active: int = Field(default=0, ge=0)
    inactive: int = Field(default=0, ge=0)
    paid: int = Field(default=0, ge=0)
    unpaid: int = Field(default=0, ge=0)
    requires_approval: int = Field(default=0, ge=0)
    no_approval_required: int = Field(default=0, ge=0)
    requires_documentation: int = Field(default=0, ge=0)
    carry_forward_enabled: int = Field(default=0, ge=0)
    encashment_enabled: int = Field(default=0, ge=0)
    accrued: int = Field(default=0, ge=0)
    available_during_probation: int = Field(default=0, ge=0)
    gender_specific: int = Field(default=0, ge=0)



# -------------------------
# Claim Type Schemas
# -------------------------


class CreateClaimTypeRequest(BaseModel):
    """
    Request schema for creating a new claim type.

    Used by:
        POST /api/v1/master-data/claim-types

    Required role:
        HR or Admin
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Claim type name",
        examples=["Travel Expenses", "Food & Beverages", "Medical Reimbursement"],
    )

    code: str = Field(
        ...,
        min_length=2,
        max_length=20,
        description="Unique claim type code",
        examples=["TRAVEL", "FOOD", "MEDICAL", "INTERNET"],
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="What expenses are covered under this claim type",
    )

    default_annual_limit: int = Field(
        ...,
        ge=0,
        description="Default annual claim limit amount per employee",
        examples=[5000],
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
        description="Auto-approve claims below or equal to this amount",
    )

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

    available_during_probation: bool = Field(
        default=True,
        description="Whether employees can submit this claim during probation",
    )

    display_order: int = Field(
        default=0,
        ge=0,
        description="Sort order in frontend dropdowns",
    )

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        return validate_master_code(value, label="Claim type code")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Claim type name cannot be empty")

        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency(value)

    @field_validator("allowed_file_types")
    @classmethod
    def validate_allowed_file_types(cls, value: list[str]) -> list[str]:
        return normalize_file_types(value)

    @model_validator(mode="after")
    def validate_claim_type_rules(self):
        """
        Validate fields that depend on each other.
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

        if (
            self.approval_threshold is not None
            and self.finance_approval_threshold is not None
            and self.finance_approval_threshold < self.approval_threshold
        ):
            raise ValueError(
                "finance_approval_threshold cannot be less than approval_threshold"
            )

        if self.auto_approve_below is not None:
            if (
                self.approval_threshold is not None
                and self.auto_approve_below > self.approval_threshold
            ):
                raise ValueError(
                    "auto_approve_below cannot be greater than approval_threshold"
                )

            if (
                self.max_claim_amount is not None
                and self.auto_approve_below > self.max_claim_amount
            ):
                raise ValueError(
                    "auto_approve_below cannot be greater than max_claim_amount"
                )

        return self


class UpdateClaimTypeRequest(BaseModel):
    """
    Request schema for updating an existing claim type.

    Used by:
        PATCH /api/v1/master-data/claim-types/{claim_type_id}

    Required role:
        HR or Admin

    Notes:
    - All fields are optional.
    - Only provided fields should be updated.
    - Full business consistency should also be checked in service layer after merging existing + update data.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    code: Optional[str] = Field(default=None, min_length=2, max_length=20)
    description: Optional[str] = Field(default=None, max_length=500)

    default_annual_limit: Optional[int] = Field(default=None, ge=0)
    default_monthly_limit: Optional[int] = Field(default=None, ge=0)
    max_claim_amount: Optional[int] = Field(default=None, ge=0)
    min_claim_amount: Optional[int] = Field(default=None, ge=0)

    requires_bill: Optional[bool] = Field(default=None)
    bill_threshold: Optional[int] = Field(default=None, ge=0)
    allowed_file_types: Optional[list[str]] = Field(default=None)
    max_file_size_mb: Optional[int] = Field(default=None, ge=1, le=25)

    requires_approval: Optional[bool] = Field(default=None)
    approval_threshold: Optional[int] = Field(default=None, ge=0)
    finance_approval_threshold: Optional[int] = Field(default=None, ge=0)
    auto_approve_below: Optional[int] = Field(default=None, ge=0)

    reimbursement_percentage: Optional[int] = Field(default=None, ge=0, le=100)
    is_taxable: Optional[bool] = Field(default=None)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)

    available_during_probation: Optional[bool] = Field(default=None)
    display_order: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = Field(default=None)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        return validate_master_code(value, label="Claim type code")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("Claim type name cannot be empty")

        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        return normalize_currency(value)

    @field_validator("allowed_file_types")
    @classmethod
    def validate_allowed_file_types(
        cls,
        value: Optional[list[str]],
    ) -> Optional[list[str]]:
        if value is None:
            return None

        return normalize_file_types(value)


class ClaimTypeListResponse(BaseModel):
    """
    Response schema for claim type list view.

    Used by:
        GET /api/v1/master-data/claim-types
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    description: Optional[str] = None

    default_annual_limit: int
    default_monthly_limit: Optional[int] = None
    max_claim_amount: Optional[int] = None
    min_claim_amount: Optional[int] = None

    requires_bill: bool
    bill_threshold: Optional[int] = None
    allowed_file_types: list[str] = Field(default_factory=list)
    max_file_size_mb: int

    requires_approval: bool
    approval_threshold: Optional[int] = None
    finance_approval_threshold: Optional[int] = None
    auto_approve_below: Optional[int] = None

    reimbursement_percentage: int
    is_taxable: bool
    currency: str

    available_during_probation: bool
    display_order: int = 0
    is_active: bool

    created_at: datetime
    updated_at: datetime


class ClaimTypeDetailResponse(ClaimTypeListResponse):
    """
    Response schema for a single claim type detail view.

    Used by:
        GET /api/v1/master-data/claim-types/{claim_type_id}
    """

    total_employees_assigned: int = Field(default=0, ge=0)
    total_claims_this_year: int = Field(default=0, ge=0)
    total_amount_claimed_this_year: int = Field(default=0, ge=0)


class ClaimTypeDropdownResponse(BaseModel):
    """
    Lightweight claim type response for frontend dropdowns.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    default_annual_limit: int
    default_monthly_limit: Optional[int] = None
    max_claim_amount: Optional[int] = None
    min_claim_amount: Optional[int] = None
    requires_bill: bool
    bill_threshold: Optional[int] = None
    allowed_file_types: list[str] = Field(default_factory=list)
    max_file_size_mb: int
    currency: str
    is_active: bool


class ClaimTypeCreatedResponse(BaseModel):
    """
    Response schema after creating a claim type.

    Used by:
        POST /api/v1/master-data/claim-types
    """

    message: str = Field(default="Claim type created successfully")
    claim_type_id: str
    claim_type: ClaimTypeListResponse


class ClaimTypeUpdatedResponse(BaseModel):
    """
    Response schema after updating a claim type.

    Used by:
        PATCH /api/v1/master-data/claim-types/{claim_type_id}
    """

    message: str = Field(default="Claim type updated successfully")
    claim_type: ClaimTypeListResponse


class ClaimTypeDeactivatedResponse(BaseModel):
    """
    Response schema after deactivating a claim type.

    Used by:
        DELETE /api/v1/master-data/claim-types/{claim_type_id}
    """

    message: str = Field(default="Claim type deactivated successfully")
    claim_type_id: str


ClaimTypeDeletedResponse = ClaimTypeDeactivatedResponse


class BulkClaimTypeImportRequest(BaseModel):
    """
    Request schema for bulk importing claim types.

    Used by:
        POST /api/v1/master-data/claim-types/bulk-import

    Required role:
        Admin only
    """

    model_config = ConfigDict(extra="forbid")

    claim_types: list[CreateClaimTypeRequest] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of claim types to create",
    )

    skip_duplicates: bool = Field(
        default=True,
        description="Skip claim types with duplicate codes instead of failing the full import",
    )


class BulkClaimTypeImportResponse(BaseModel):
    """
    Response schema for bulk claim type import operation.
    """

    message: str
    created_count: int = Field(..., ge=0)
    skipped_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    created_ids: list[str] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)


class ClaimTypeListQuery(BaseModel):
    """
    Query parameters for listing claim types.

    Used by:
        GET /api/v1/master-data/claim-types
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    is_active: Optional[bool] = Field(default=None)
    requires_bill: Optional[bool] = Field(default=None)
    requires_approval: Optional[bool] = Field(default=None)
    is_taxable: Optional[bool] = Field(default=None)
    available_during_probation: Optional[bool] = Field(default=None)
    currency: Optional[str] = Field(default=None)

    search: Optional[str] = Field(default=None, min_length=2, max_length=100)

    sort_by: Literal[
        "display_order",
        "name",
        "code",
        "default_annual_limit",
        "default_monthly_limit",
        "max_claim_amount",
        "requires_bill",
        "requires_approval",
        "is_taxable",
        "created_at",
        "updated_at",
    ] = Field(default="display_order")

    sort_order: Literal["asc", "desc"] = Field(default="asc")
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        return normalize_currency(value)

    @field_validator("search")
    @classmethod
    def clean_search(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class ClaimTypeStatisticsResponse(BaseModel):
    """
    Statistics response for claim type dashboard.

    Used by:
        GET /api/v1/master-data/claim-types/statistics
    """

    total: int = Field(default=0, ge=0)
    active: int = Field(default=0, ge=0)
    inactive: int = Field(default=0, ge=0)
    requires_bill: int = Field(default=0, ge=0)
    no_bill_required: int = Field(default=0, ge=0)
    requires_approval: int = Field(default=0, ge=0)
    no_approval_required: int = Field(default=0, ge=0)
    taxable: int = Field(default=0, ge=0)
    non_taxable: int = Field(default=0, ge=0)
    available_during_probation: int = Field(default=0, ge=0)
    auto_approval_enabled: int = Field(default=0, ge=0)


# -------------------------
# Holiday Schemas
# -------------------------


class CreateHolidayRequest(BaseModel):
    """
    Request schema for creating a new holiday.

    Used by:
        POST /api/v1/master-data/holidays

    Required role:
        HR or Admin
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    date: Date = Field(
        ...,
        description="Holiday date",
        examples=["2026-08-15"],
    )

    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Holiday name",
        examples=["Independence Day", "Holi", "Diwali"],
    )

    type: Literal[
        "national",
        "festival",
        "company",
        "optional",
        "regional",
    ] = Field(
        default="national",
        description="Holiday type",
        examples=["national", "festival", "company", "optional", "regional"],
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Holiday description or significance",
    )

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

    location: Optional[str] = Field(
        default=None,
        max_length=100,
        description=(
            "Location or region this holiday applies to. "
            "Use None or All for company-wide holidays."
        ),
        examples=["All", "Noida", "Mumbai", "Delhi"],
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

    is_optional: bool = Field(
        default=False,
        description="Whether this is an optional holiday",
    )

    optional_limit_per_employee: Optional[int] = Field(
        default=None,
        ge=1,
        description="How many optional holidays each employee can take per year",
    )

    display_order: int = Field(
        default=0,
        ge=0,
        description="Sort order in frontend calendar",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """
        Normalize holiday name.

        Do not force title case because some holiday names may have
        specific formatting like Eid-ul-Fitr or Dr. Ambedkar Jayanti.
        """
        value = value.strip()

        if not value:
            raise ValueError("Holiday name cannot be empty")

        return value

    @field_validator("description", "location")
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        """
        Normalize optional text fields.
        """
        return normalize_optional_text(value)

    @field_validator("location")
    @classmethod
    def normalize_location(cls, value: Optional[str]) -> Optional[str]:
        """
        Normalize location value.

        Rules:
        - None means company-wide/all locations.
        - Empty string becomes None.
        - all/ALL becomes All.
        """
        if value is None:
            return None

        value = value.strip()

        if not value:
            return None

        if value.lower() == "all":
            return "All"

        return value

    @model_validator(mode="after")
    def validate_holiday_rules(self):
        """
        Validate cross-field holiday rules.
        """

        if self.year is None:
            self.year = self.date.year

        if self.year != self.date.year:
            raise ValueError("year must match date.year")

        if self.is_half_day and not self.is_working_day:
            raise ValueError(
                "is_half_day can only be True when is_working_day is also True"
            )

        if self.type == "optional":
            self.is_optional = True

        if self.is_optional and self.type != "optional":
            self.type = "optional"

        if self.is_optional:
            if self.optional_limit_per_employee is None:
                raise ValueError(
                    "optional_limit_per_employee is required when is_optional=True"
                )

            if self.optional_limit_per_employee <= 0:
                raise ValueError(
                    "optional_limit_per_employee must be greater than 0"
                )
        else:
            if self.optional_limit_per_employee is not None:
                raise ValueError(
                    "optional_limit_per_employee must be None when is_optional=False"
                )

        return self


class UpdateHolidayRequest(BaseModel):
    """
    Request schema for updating an existing holiday.

    Used by:
        PATCH /api/v1/master-data/holidays/{holiday_id}

    Required role:
        HR or Admin

    Note:
        This schema validates field format only.
        Full cross-field validation should happen in MasterDataService
        after merging existing holiday data with update data.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    date: Optional[Date] = Field(
        default=None,
        description="Updated holiday date",
    )

    name: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=100,
        description="Updated holiday name",
    )

    type: Optional[
        Literal[
            "national",
            "festival",
            "company",
            "optional",
            "regional",
        ]
    ] = Field(
        default=None,
        description="Updated holiday type",
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Updated holiday description",
    )

    is_working_day: Optional[bool] = Field(
        default=None,
        description="Whether this date is treated as a working day",
    )

    is_half_day: Optional[bool] = Field(
        default=None,
        description="Whether this is a half-day holiday",
    )

    location: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Updated holiday location or region",
    )

    year: Optional[int] = Field(
        default=None,
        ge=2020,
        le=2100,
        description="Updated holiday year",
    )

    is_optional: Optional[bool] = Field(
        default=None,
        description="Whether this is an optional holiday",
    )

    optional_limit_per_employee: Optional[int] = Field(
        default=None,
        ge=1,
        description="Updated optional holiday yearly limit per employee",
    )

    display_order: Optional[int] = Field(
        default=None,
        ge=0,
        description="Updated frontend sort order",
    )

    is_active: Optional[bool] = Field(
        default=None,
        description="Activate or deactivate holiday",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("Holiday name cannot be empty")

        return value

    @field_validator("description", "location")
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("location")
    @classmethod
    def normalize_location(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        value = value.strip()

        if not value:
            return None

        if value.lower() == "all":
            return "All"

        return value


class HolidayListResponse(BaseModel):
    """
    Response schema for holiday list view.

    Used by:
        GET /api/v1/master-data/holidays
    """

    model_config = ConfigDict(from_attributes=True)

    id: str

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

    created_at: datetime
    updated_at: datetime


class HolidayDetailResponse(HolidayListResponse):
    """
    Response schema for a single holiday detail view.

    Used by:
        GET /api/v1/master-data/holidays/{holiday_id}
    """

    created_by: Optional[str] = None
    updated_by: Optional[str] = None


class HolidayCalendarResponse(BaseModel):
    """
    Lightweight holiday response for frontend calendar widget.

    Used by:
        GET /api/v1/master-data/holidays/calendar
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
    Lightweight holiday response for dropdowns or quick selectors.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    date: Date
    type: str
    location: Optional[str] = None
    is_optional: bool


class HolidayCreatedResponse(BaseModel):
    """
    Response schema after creating a holiday.

    Used by:
        POST /api/v1/master-data/holidays
    """

    message: str = Field(default="Holiday created successfully")
    holiday_id: str
    holiday: HolidayListResponse


class HolidayUpdatedResponse(BaseModel):
    """
    Response schema after updating a holiday.

    Used by:
        PATCH /api/v1/master-data/holidays/{holiday_id}
    """

    message: str = Field(default="Holiday updated successfully")
    holiday: HolidayListResponse


class HolidayDeactivatedResponse(BaseModel):
    """
    Response schema after deactivating a holiday.

    Used by:
        DELETE /api/v1/master-data/holidays/{holiday_id}
    """

    message: str = Field(default="Holiday deactivated successfully")
    holiday_id: str


HolidayDeletedResponse = HolidayDeactivatedResponse


class BulkHolidayImportRequest(BaseModel):
    """
    Request schema for bulk importing holidays.

    Used by:
        POST /api/v1/master-data/holidays/bulk-import

    Required role:
        Admin only
    """

    model_config = ConfigDict(extra="forbid")

    holidays: list[CreateHolidayRequest] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="List of holidays to create",
    )

    skip_duplicates: bool = Field(
        default=True,
        description=(
            "Skip duplicate holidays instead of failing the full import. "
            "Duplicate detection should be handled by service/repository using date, name, and location."
        ),
    )


class BulkHolidayImportResponse(BaseModel):
    """
    Response schema for bulk holiday import operation.
    """

    message: str
    created_count: int = Field(..., ge=0)
    skipped_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    created_ids: list[str] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)


class HolidayListQuery(BaseModel):
    """
    Query parameters for listing holidays.

    Used by:
        GET /api/v1/master-data/holidays
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    year: Optional[int] = Field(default=None, ge=2020, le=2100)
    month: Optional[int] = Field(default=None, ge=1, le=12)

    type: Optional[
        Literal[
            "national",
            "festival",
            "company",
            "optional",
            "regional",
        ]
    ] = Field(
        default=None,
        description="Filter by holiday type",
    )

    location: Optional[str] = Field(default=None)

    is_optional: Optional[bool] = Field(default=None)
    is_working_day: Optional[bool] = Field(default=None)
    is_half_day: Optional[bool] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)

    from_date: Optional[Date] = Field(
        default=None,
        description="Filter holidays from this date",
    )

    to_date: Optional[Date] = Field(
        default=None,
        description="Filter holidays up to this date",
    )

    search: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=100,
        description="Search by holiday name, type, location, or description",
    )

    sort_by: Literal[
        "date",
        "name",
        "type",
        "year",
        "location",
        "display_order",
        "created_at",
        "updated_at",
    ] = Field(default="date")

    sort_order: Literal["asc", "desc"] = Field(default="asc")

    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)

    @field_validator("location", "search")
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.from_date and self.to_date:
            if self.from_date > self.to_date:
                raise ValueError("from_date cannot be after to_date")

        return self


class HolidayStatisticsResponse(BaseModel):
    """
    Statistics response for holiday dashboard.

    Used by:
        GET /api/v1/master-data/holidays/statistics
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

    holidays_per_year: dict[int, int] = Field(default_factory=dict)
    holidays_per_location: dict[str, int] = Field(default_factory=dict)


# -------------------------
# Generic API Responses
# -------------------------


class SuccessResponse(BaseModel):
    """
    Generic success response for operations that do not return full data.

    Used for:
    - Status updates
    - Simple confirmations
    - Utility endpoints
    """

    success: bool = Field(default=True)
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ErrorDetail(BaseModel):
    """
    Detailed error information.

    Used for validation errors and business logic errors.
    """

    field: Optional[str] = Field(
        default=None,
        description="Field name that caused the error",
    )

    message: str = Field(
        ...,
        description="Human-readable error message",
    )

    error_code: Optional[str] = Field(
        default=None,
        description="Machine-readable error code",
    )


class ErrorResponse(BaseModel):
    """
    Standard error response format.

    Used by frontend to show clean and consistent error messages.
    """

    success: bool = Field(default=False)

    message: str = Field(
        ...,
        description="High-level error message",
    )

    error_code: str = Field(
        ...,
        description="Machine-readable error code for frontend handling",
    )

    details: Optional[list[ErrorDetail]] = Field(
        default=None,
        description="Detailed error information",
    )

    timestamp: datetime = Field(default_factory=datetime.utcnow)