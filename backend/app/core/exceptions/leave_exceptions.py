from typing import Any

from .base import BaseAppException


class LeaveException(BaseAppException):
    def __init__(
        self,
        message: str,
        error_code: str = "LEAVE_BASE",
        status_code: int = 422,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            details=details,
        )


class InsufficientLeaveBalanceException(LeaveException):
    def __init__(
        self,
        message: str = "Insufficient leave balance for the requested leave type.",
        current_balance: float | None = None,
        requested_days: float | None = None,
        leave_type: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if current_balance is not None:
            merged_details["current_balance"] = current_balance
        if requested_days is not None:
            merged_details["requested_days"] = requested_days
        if leave_type:
            merged_details["leave_type"] = leave_type
        super().__init__(
            message=message,
            error_code="LEAVE_001",
            status_code=422,
            details=merged_details,
        )


class LeaveOverlapException(LeaveException):
    def __init__(
        self,
        message: str = "The requested dates overlap with an existing approved leave.",
        conflicting_leave_id: str | None = None,
        conflicting_from_date: str | None = None,
        conflicting_to_date: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if conflicting_leave_id:
            merged_details["conflicting_leave_id"] = conflicting_leave_id
        if conflicting_from_date:
            merged_details["conflicting_from_date"] = conflicting_from_date
        if conflicting_to_date:
            merged_details["conflicting_to_date"] = conflicting_to_date
        super().__init__(
            message=message,
            error_code="LEAVE_002",
            status_code=409,
            details=merged_details,
        )


class RestrictedLeaveTypeException(LeaveException):
    def __init__(
        self,
        message: str = "This leave type requires special conditions or documentation.",
        required_documents: list[str] | None = None,
        applicable_policy: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if required_documents:
            merged_details["required_documents"] = required_documents
        if applicable_policy:
            merged_details["applicable_policy"] = applicable_policy
        super().__init__(
            message=message,
            error_code="LEAVE_003",
            status_code=403,
            details=merged_details,
        )