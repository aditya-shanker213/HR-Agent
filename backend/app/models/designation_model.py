"""
Designation master data model.

Stores all job titles/positions.

Employee profiles should reference designation_id instead of hard-coded
designation strings like "Software Engineer", "AI Intern", or "HR Manager".

Pattern:
- HR/Admin can create and update designations through API.
- All authenticated users can read active designations for dropdowns.
- Designations are soft-deleted using is_active=False.
- Designation code is unique and stable.
- Optional level field supports career progression tracking.
- Optional department_id supports department-specific job titles.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Designation(BaseModel):
    """
    Designation document model for the designations collection.

    Represents job titles/positions such as:
    - Software Engineer
    - Data Science Intern
    - HR Manager
    - Team Lead
    - AI/ML Engineer
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Designation name, for example Software Engineer or HR Manager",
    )

    code: str = Field(
        ...,
        min_length=2,
        max_length=20,
        description="Unique short code, for example SWE, HRM, DS, TL, AI_ENG",
    )

    level: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description=(
            "Career level for progression tracking. "
            "Example: 1=Junior, 2=Mid, 3=Senior, 4=Lead, 5=Principal"
        ),
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Designation description, responsibilities, and requirements",
    )

    department_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional department ID if designation is department-specific. "
            "Leave None for cross-department designations like Manager or Intern."
        ),
    )

    display_order: int = Field(
        default=0,
        ge=0,
        description="Used to sort designations in frontend dropdowns",
    )

    is_active: bool = Field(
        default=True,
        description="Soft delete flag. Inactive designations are hidden from normal dropdowns",
    )

    created_by: Optional[str] = Field(
        default=None,
        description="User ID or employee ID of the HR/Admin who created this designation",
    )

    updated_by: Optional[str] = Field(
        default=None,
        description="User ID or employee ID of the HR/Admin who last updated this designation",
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Creation timestamp",
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp",
    )

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        """
        Validate designation code.

        Rules:
        - Uppercase letters, numbers, and underscores only
        - No spaces
        - No special characters except underscore
        """
        value = value.strip().upper()

        if not value:
            raise ValueError("Designation code cannot be empty")

        if not value.replace("_", "").isalnum():
            raise ValueError(
                "Designation code can only contain uppercase letters, numbers, and underscores"
            )

        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """
        Normalize designation name.

        Do not force title case because names like AI/ML Engineer, R&D Lead,
        VP Engineering, and CTO should keep their intended formatting.
        """
        value = value.strip()

        if not value:
            raise ValueError("Designation name cannot be empty")

        return value

    @field_validator(
        "description",
        "department_id",
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


class DesignationInDB(Designation):
    """
    Designation model as stored in MongoDB with _id field.

    Used internally by repositories.
    """

    id: Optional[str] = Field(default=None, alias="_id")

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class DesignationResponse(BaseModel):
    """
    Safe designation response for API output.

    Used by frontend dropdowns, admin pages, and employee profile pages.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Designation ID")
    name: str
    code: str
    level: Optional[int] = None
    description: Optional[str] = None
    department_id: Optional[str] = None
    display_order: int = 0
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DesignationWithDepartment(DesignationResponse):
    """
    Designation response enriched with department data.

    Useful for admin dashboards showing:
    Software Engineer - Engineering Department
    """

    department_name: Optional[str] = Field(
        default=None,
        description="Name of associated department if department_id is set",
    )

    department_code: Optional[str] = Field(
        default=None,
        description="Code of associated department if department_id is set",
    )


class DesignationListItem(BaseModel):
    """
    Lightweight designation item for dropdown lists.

    Minimal fields for performance when loading dropdowns.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    level: Optional[int] = None
    department_id: Optional[str] = None
    is_active: bool