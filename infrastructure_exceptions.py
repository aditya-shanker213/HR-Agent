from typing import Any

from .base import BaseAppException


class InfrastructureException(BaseAppException):
    def __init__(
        self,
        message: str,
        error_code: str = "INFRA_BASE",
        status_code: int = 503,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            details=details,
        )


class DatabaseConnectionException(InfrastructureException):
    def __init__(
        self,
        message: str = "Database is temporarily unavailable. Please try again shortly.",
        database: str = "mongodb",
        read_replica_attempted: bool = False,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        merged_details["database"] = database
        merged_details["read_replica_attempted"] = read_replica_attempted
        super().__init__(
            message=message,
            error_code="DB_001",
            status_code=503,
            details=merged_details,
        )


class DuplicateRecordException(InfrastructureException):
    def __init__(
        self,
        message: str = "A record with the same unique values already exists.",
        duplicate_field: str | None = None,
        collection: str | None = None,
        existing_record_id: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if duplicate_field:
            merged_details["duplicate_field"] = duplicate_field
        if collection:
            merged_details["collection"] = collection
        if existing_record_id:
            merged_details["existing_record_id"] = existing_record_id
        super().__init__(
            message=message,
            error_code="DB_002",
            status_code=409,
            details=merged_details,
        )


class ServiceUnavailableException(InfrastructureException):
    def __init__(
        self,
        message: str = "A required external service is currently unavailable.",
        service_name: str | None = None,
        circuit_open: bool = False,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if service_name:
            merged_details["service_name"] = service_name
        merged_details["circuit_open"] = circuit_open
        super().__init__(
            message=message,
            error_code="INFRA_001",
            status_code=503,
            details=merged_details,
        )


class APITimeoutException(InfrastructureException):
    def __init__(
        self,
        message: str = "An external API call timed out.",
        service_name: str | None = None,
        timeout_ms: int | None = None,
        endpoint: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if service_name:
            merged_details["service_name"] = service_name
        if timeout_ms is not None:
            merged_details["timeout_ms"] = timeout_ms
        if endpoint:
            merged_details["endpoint"] = endpoint
        super().__init__(
            message=message,
            error_code="INFRA_002",
            status_code=504,
            details=merged_details,
        )