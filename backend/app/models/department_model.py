"""
Department master data model.

Stores all company departments/teams.

Employee profiles should reference department_id instead of hard-coded
department strings like "Engineering" or "HR".

Pattern:
- HR/Admin can create and update departments through API.
- All authenticated users can read active departments for dropdowns.
- Departments are soft-deleted using is_active=False.
- Department code is unique and stable.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator


class Department(BaseModel):
    """
    Department document model for the departments collection.

    Represents organizational units such as:
    - Engineering
    - Human Resources
    - Finance
    - Sales
    - AI/ML Team
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,  # Auto-strip all strings
        validate_assignment=True,    # Validate on field updates
    )

    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Department name, for example Engineering or Human Resources",
    )

    code: str = Field(
        ...,
        min_length=2,
        max_length=20,
        description="Unique short code, for example ENG, HR, FIN, AI_ML",
    )

    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Department description and responsibilities",
    )

    head_id: Optional[str] = Field(
        default=None,
        description="Employee ID of department head or manager",
    )

    parent_id: Optional[str] = Field(
        default=None,
        description="Parent department ID for nested departments",
    )

    location: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Department location or branch, for example Noida, Mumbai, Remote",
    )

    display_order: int = Field(
        default=0,
        ge=0,
        description="Used to sort departments in frontend dropdowns",
    )

    is_active: bool = Field(
        default=True,
        description="Soft delete flag. Inactive departments are hidden from normal dropdowns",
    )

    created_by: Optional[str] = Field(
        default=None,
        description="User ID or employee ID of the HR/Admin who created this department",
    )

    updated_by: Optional[str] = Field(
        default=None,
        description="User ID or employee ID of the HR/Admin who last updated this department",
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
        Validate department code.

        Rules:
        - Uppercase letters, numbers, and underscores only
        - No spaces
        - No special characters except underscore
        """
        value = value.strip().upper()

        if not value:
            raise ValueError("Department code cannot be empty")

        if not value.replace("_", "").isalnum():
            raise ValueError(
                "Department code can only contain uppercase letters, numbers, and underscores"
            )

        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """
        Normalize department name.

        Do not force title case because names like AI/ML, R&D, HR, and IT
        should keep their intended formatting.
        """
        value = value.strip()

        if not value:
            raise ValueError("Department name cannot be empty")

        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        value = value.strip()
        return value or None

    @field_validator("location")
    @classmethod
    def validate_location(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        value = value.strip()
        return value or None


class DepartmentInDB(Department):
    """
    Department model as stored in MongoDB with _id field.

    Used internally by repositories.
    """

    id: Optional[str] = Field(default=None, alias="_id")

    model_config = ConfigDict(populate_by_name=True)


class DepartmentResponse(BaseModel):
    """
    Safe department response for API output.

    Used by frontend dropdowns, admin pages, and employee profile pages.
    """

    id: str = Field(..., description="Department ID")
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


class DepartmentWithHead(DepartmentResponse):
    """
    Department response enriched with department head data.

    Useful for admin dashboards or organization charts.
    """

    head_name: Optional[str] = Field(
        default=None,
        description="Full name of department head",
    )

    head_email: Optional[str] = Field(
        default=None,
        description="Email of department head",
    )


class DepartmentTreeResponse(DepartmentResponse):
    """
    Department response for hierarchy/tree UI.

    Useful when you later support nested departments like:
    Engineering
      - Backend
      - Frontend
      - AI/ML
    """

    children_count: int = Field(
        default=0,
        description="Number of active child departments",
    )