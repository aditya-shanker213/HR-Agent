"""
Request and response schemas for master data APIs.

This file defines the API contract for master data modules.

Current scope:
- Departments

Later scope:
- Designations
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
from typing import Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# -------------------------
# Shared validators/helpers
# -------------------------


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    """
    Strip optional text fields.

    Empty string should become None so MongoDB does not store useless "" values.
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
    - No special characters
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
        description="Employee ID of department head",
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
        description="Updated department head employee ID",
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

    Purpose:
        Lightweight department data for dropdowns, tables, and admin list pages.
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

    Includes extra calculated/enriched fields.
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


class DepartmentCreatedResponse(BaseModel):
    """
    Response schema after creating a department.

    Used by:
        POST /api/v1/master-data/departments
    """

    message: str = Field(
        default="Department created successfully",
        description="Success message",
    )

    department_id: str = Field(
        ...,
        description="ID of newly created department",
    )

    department: DepartmentListResponse = Field(
        ...,
        description="Created department data",
    )


class DepartmentUpdatedResponse(BaseModel):
    """
    Response schema after updating a department.

    Used by:
        PATCH /api/v1/master-data/departments/{department_id}
    """

    message: str = Field(
        default="Department updated successfully",
        description="Success message",
    )

    department: DepartmentListResponse = Field(
        ...,
        description="Updated department data",
    )


class DepartmentDeactivatedResponse(BaseModel):
    """
    Response schema after deactivating a department.

    Used by:
        DELETE /api/v1/master-data/departments/{department_id}

    Note:
        This is a soft delete. It sets is_active=False.
        The department document remains in MongoDB.
    """

    message: str = Field(
        default="Department deactivated successfully",
        description="Success message",
    )

    department_id: str = Field(
        ...,
        description="ID of deactivated department",
    )


# Backward-compatible alias if you already used DepartmentDeletedResponse in routes.
DepartmentDeletedResponse = DepartmentDeactivatedResponse


# -------------------------
# Bulk Operations
# -------------------------


class BulkDepartmentImportRequest(BaseModel):
    """
    Request schema for bulk importing departments.

    Used by:
        POST /api/v1/master-data/departments/bulk-import

    Required role:
        Admin only

    Purpose:
        Useful during first company setup or migration from another HRMS.
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

    created_count: int = Field(
        ...,
        ge=0,
        description="Number of departments successfully created",
    )

    skipped_count: int = Field(
        default=0,
        ge=0,
        description="Number of departments skipped due to duplicate codes",
    )

    failed_count: int = Field(
        default=0,
        ge=0,
        description="Number of departments that failed validation",
    )

    created_ids: list[str] = Field(
        default_factory=list,
        description="List of created department IDs",
    )

    errors: list[dict] = Field(
        default_factory=list,
        description="List of validation errors for failed departments",
    )


# -------------------------
# Query Parameters
# -------------------------


class DepartmentListQuery(BaseModel):
    """
    Query parameters for listing departments.

    Used by:
        GET /api/v1/master-data/departments

    Example:
        /api/v1/master-data/departments?is_active=true&location=Noida
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
        description="Search in department name, code, or description",
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