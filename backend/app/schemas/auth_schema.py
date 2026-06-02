"""
Authentication request and response schemas.

These schemas validate request bodies and format auth responses.
They do not contain database logic.
"""

import re
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


def validate_password_strength(password: str) -> str:
    """
    Password strength rules:
    - At least 8 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 number
    - At least 1 special character
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")

    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")

    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")

    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one number")

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise ValueError("Password must contain at least one special character")

    return password


def validate_otp_code(otp: str) -> str:
    """OTP must be exactly 6 digits."""
    if not otp.isdigit():
        raise ValueError("OTP must contain only digits")

    if len(otp) != 6:
        raise ValueError("OTP must be exactly 6 digits")

    return otp


class SafeUserResponse(BaseModel):
    """
    Safe user response schema.

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
    role: str
    is_active: bool = True
    is_email_verified: bool = False
    is_phone_verified: bool = False


class SignupOtpRequest(BaseModel):
    """
    Request to send OTP for signup.

    User account should not be created here.
    User should be created only after OTP verification.
    """

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        """Username can contain only letters, numbers, and underscores."""
        value = value.strip().lower()

        if not re.match(r"^[a-zA-Z0-9_]+$", value):
            raise ValueError("Username can only contain letters, numbers, and underscores")

        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_strength(value)


class SignupVerifyRequest(BaseModel):
    """
    Request to verify OTP and complete signup.

    User will be created only after OTP is verified.
    """

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)
    otp: str = Field(..., min_length=6, max_length=6)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip().lower()

        if not re.match(r"^[a-zA-Z0-9_]+$", value):
            raise ValueError("Username can only contain letters, numbers, and underscores")

        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_strength(value)

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, value: str) -> str:
        return validate_otp_code(value)

    @model_validator(mode="after")
    def validate_password_match(self):
        if self.password != self.confirm_password:
            raise ValueError("Password and confirm password do not match")
        return self


class LoginRequest(BaseModel):
    """Login credentials."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        """Normalize username for case-insensitive login."""
        return value.strip().lower()


class LoginResponse(BaseModel):
    """Successful login response with JWT token."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: SafeUserResponse


class ForgotPasswordOtpRequest(BaseModel):
    """Request to send OTP for password reset."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Request to reset password with OTP."""

    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, value: str) -> str:
        return validate_otp_code(value)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password_strength(value)

    @model_validator(mode="after")
    def validate_password_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("New password and confirm password do not match")
        return self


class RefreshTokenRequest(BaseModel):
    """Request to create a new access token using refresh token."""

    refresh_token: str = Field(..., min_length=10)


class RefreshTokenResponse(BaseModel):
    """Response after refreshing access token."""

    access_token: str
    token_type: str = "bearer"


class OtpResponse(BaseModel):
    """Response after OTP is sent."""

    message: str
    email: EmailStr
    expires_in_minutes: int
    dev_otp: Optional[str] = None


class SignupResponse(BaseModel):
    """Response after successful signup."""

    message: str
    user: SafeUserResponse


class PasswordResetResponse(BaseModel):
    """Response after successful password reset."""

    message: str