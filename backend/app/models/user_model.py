"""
User model for authentication and basic account profile.

This model is separate from employee_model.py.
- user_model.py stores login/authentication data.
- employee_model.py stores HR-specific employment data like department,
  manager, leave balance, claim limits, and payroll mapping.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    """User roles for access control."""
    EMPLOYEE = "employee"
    MANAGER = "manager"
    HR = "hr"
    ADMIN = "admin"


class User(BaseModel):
    """
    User document model for the users collection in MongoDB.

    This represents the authentication account.
    Employee-specific data should stay in the employees collection.
    """

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr

    # Optional now, useful later for phone OTP / step-up authentication
    phone: Optional[str] = None

    # Never expose this in API responses
    password_hash: str

    role: UserRole = UserRole.EMPLOYEE

    is_active: bool = True
    is_email_verified: bool = False
    is_phone_verified: bool = False

    # Security tracking
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = None
    password_updated_at: Optional[datetime] = None

    # Audit fields
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None


class UserInDB(User):
    """
    User model as stored in MongoDB with _id field.
    Used internally by repositories.
    """

    id: Optional[str] = Field(None, alias="_id")

    class Config:
        populate_by_name = True


class SafeUser(BaseModel):
    """
    Safe user model for API responses.

    Never include:
    - password_hash
    - failed_login_attempts
    - locked_until
    - internal security fields
    """

    id: Optional[str] = None
    username: str
    email: EmailStr
    phone: Optional[str] = None
    role: UserRole
    is_active: bool
    is_email_verified: bool
    is_phone_verified: bool
    created_at: datetime
    last_login: Optional[datetime] = None