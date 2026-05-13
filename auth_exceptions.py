from typing import Any

from .base import BaseAppException


class AuthenticationException(BaseAppException):
    def __init__(
        self,
        message: str,
        error_code: str = "AUTH_BASE",
        status_code: int = 401,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            details=details,
        )


class InvalidTokenException(AuthenticationException):
    def __init__(
        self,
        message: str = "Authentication failed. The token is invalid or malformed.",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            error_code="AUTH_001",
            status_code=401,
            details=details,
        )


class ExpiredTokenException(AuthenticationException):
    def __init__(
        self,
        message: str = "Your session has expired. Please refresh your token or log in again.",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            error_code="AUTH_002",
            status_code=401,
            details=details,
        )


class MFAValidationException(AuthenticationException):
    def __init__(
        self,
        message: str = "OTP or MFA challenge validation failed.",
        remaining_attempts: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if remaining_attempts is not None:
            merged_details["remaining_attempts"] = remaining_attempts
        super().__init__(
            message=message,
            error_code="AUTH_003",
            status_code=401,
            details=merged_details,
        )