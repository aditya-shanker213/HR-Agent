from typing import Any

from .base import BaseAppException


class SecurityException(BaseAppException):
    def __init__(
        self,
        message: str,
        error_code: str = "SEC_BASE",
        status_code: int = 403,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            details=details,
        )


class RateLimitExceededException(SecurityException):
    def __init__(
        self,
        message: str = "Too many requests. Please wait before trying again.",
        retry_after_seconds: int | None = None,
        limit_type: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if retry_after_seconds is not None:
            merged_details["retry_after_seconds"] = retry_after_seconds
        if limit_type:
            merged_details["limit_type"] = limit_type
        super().__init__(
            message=message,
            error_code="SEC_001",
            status_code=429,
            details=merged_details,
        )


class PIILeakageException(SecurityException):
    def __init__(
        self,
        message: str = "Response blocked due to detected PII in the output.",
        pii_type: str | None = None,
        blocked_field: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if pii_type:
            merged_details["pii_type"] = pii_type
        if blocked_field:
            merged_details["blocked_field"] = blocked_field
        super().__init__(
            message=message,
            error_code="SEC_002",
            status_code=500,
            details=merged_details,
        )


class SuspiciousActivityException(SecurityException):
    def __init__(
        self,
        message: str = "Unusual access pattern detected. The operation has been blocked.",
        pattern: str | None = None,
        session_invalidated: bool = False,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if pattern:
            merged_details["pattern"] = pattern
        merged_details["session_invalidated"] = session_invalidated
        super().__init__(
            message=message,
            error_code="SEC_003",
            status_code=403,
            details=merged_details,
        )


class SQLInjectionException(SecurityException):
    def __init__(
        self,
        message: str = "Request blocked due to detected injection patterns.",
        blocked_pattern: str | None = None,
        source_blocked: bool = False,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if blocked_pattern:
            merged_details["blocked_pattern"] = blocked_pattern
        merged_details["source_blocked"] = source_blocked
        super().__init__(
            message=message,
            error_code="SEC_004",
            status_code=400,
            details=merged_details,
        )