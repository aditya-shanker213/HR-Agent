"""
Request and response schemas for master data APIs.

This file defines the API contract for master data modules.

Current scope:
- Departments
- Designations

Later scope:
- Leave Types
- Claim Types
- Company Settings
- Holiday Calendar

Important:
- Schemas are used by FastAPI routes.
- Models are used for MongoDB document structure.
- Do not put database logic here.
- Do not put business logic here.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    Notes:
    - created_by should not come from frontend.
    - Backend should set created_by from current logged-in user.
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

        # Do not title-case because names like AI/ML, R&D, HR should be preserved.
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

    Notes:
    - All fields are optional.
    - Only provided fields should be updated.
    - updated_by should be set by backend from current logged-in user.
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

    Note:
        This is a soft delete. It sets is_active=False.
    """

    message: str = Field(default="Department deactivated successfully")
    department_id: str


# Backward-compatible alias if you already used DepartmentDeletedResponse in routes.
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

    is_active: Optional[bool] = Field(
        default=None,
        description="Filter by active status. Omit to get all departments.",
    )

    location: Optional[str] = Field(
        default=None,
        description="Filter by location or branch",
    )

    parent_id: Optional[str] = Field(
        default=None,
        description="Filter by parent department ID",
    )

    search: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=100,
        description="Search in department name, code, description, or location",
    )

    sort_by: Literal["display_order", "name", "code", "created_at", "updated_at"] = Field(
        default="display_order",
        description="Sort field",
    )

    sort_order: Literal["asc", "desc"] = Field(
        default="asc",
        description="Sort order",
    )

    skip: int = Field(
        default=0,
        ge=0,
        description="Number of records to skip for pagination",
    )

    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of records to return",
    )

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

    Notes:
    - created_by should not come from frontend.
    - Backend should set created_by from current logged-in user.
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

        # Do not title-case because names like AI/ML Engineer, R&D Lead, VP should be preserved.
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

    Notes:
    - All fields are optional.
    - Only provided fields should be updated.
    - updated_by should be set by backend from current logged-in user.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    name: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=100,
        description="Updated designation name",
    )

    code: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=20,
        description="Updated designation code",
    )

    level: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Updated career level",
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Updated designation description",
    )

    department_id: Optional[str] = Field(
        default=None,
        description="Updated department ID",
    )

    display_order: Optional[int] = Field(
        default=None,
        ge=0,
        description="Updated sort order",
    )

    is_active: Optional[bool] = Field(
        default=None,
        description="Activate or deactivate designation",
    )

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

    department_name: Optional[str] = Field(
        default=None,
        description="Name of associated department if department_id is set",
    )

    department_code: Optional[str] = Field(
        default=None,
        description="Code of associated department if department_id is set",
    )

    employee_count: int = Field(
        default=0,
        ge=0,
        description="Number of active employees with this designation",
    )


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

    Note:
        This is a soft delete. It sets is_active=False.
    """

    message: str = Field(default="Designation deactivated successfully")
    designation_id: str


# Backward-compatible alias if you later use this name in routes.
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

    is_active: Optional[bool] = Field(
        default=None,
        description="Filter by active status. Omit to get all designations.",
    )

    department_id: Optional[str] = Field(
        default=None,
        description="Filter by department ID",
    )

    level: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Filter by career level",
    )

    search: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=100,
        description="Search in designation name, code, or description",
    )

    sort_by: Literal[
        "display_order",
        "name",
        "code",
        "level",
        "created_at",
        "updated_at",
    ] = Field(
        default="display_order",
        description="Sort field",
    )

    sort_order: Literal["asc", "desc"] = Field(
        default="asc",
        description="Sort order",
    )

    skip: int = Field(
        default=0,
        ge=0,
        description="Number of records to skip for pagination",
    )

    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of records to return",
    )

    @field_validator("department_id", "search")
    @classmethod
    def clean_optional_text_fields(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


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