from typing import Any

from .base import BaseAppException


class AuthorizationException(BaseAppException):
    def __init__(
        self,
        message: str,
        error_code: str = "AUTHZ_BASE",
        status_code: int = 403,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            details=details,
        )


class PermissionDeniedException(AuthorizationException):
    def __init__(
        self,
        message: str = "You do not have permission to perform this action.",
        required_permission: str | None = None,
        current_role: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if required_permission:
            merged_details["required_permission"] = required_permission
        if current_role:
            merged_details["current_role"] = current_role
        super().__init__(
            message=message,
            error_code="AUTHZ_001",
            status_code=403,
            details=merged_details,
        )


class RoleRestrictionException(AuthorizationException):
    def __init__(
        self,
        message: str = "Your role does not have sufficient privilege for this operation.",
        required_tier: str | None = None,
        current_role: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if required_tier:
            merged_details["required_tier"] = required_tier
        if current_role:
            merged_details["current_role"] = current_role
        super().__init__(
            message=message,
            error_code="AUTHZ_002",
            status_code=403,
            details=merged_details,
        )


class SensitiveActionException(AuthorizationException):
    def __init__(
        self,
        message: str = "This action requires secondary approval before execution.",
        approval_workflow_id: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {"approval_required": True}
        if approval_workflow_id:
            merged_details["approval_workflow_id"] = approval_workflow_id
        super().__init__(
            message=message,
            error_code="AUTHZ_003",
            status_code=403,
            details=merged_details,
        )


class HRApprovalRequiredException(AuthorizationException):
    def __init__(
        self,
        message: str = "This operation requires formal HR escalation before proceeding.",
        hr_action_required: str | None = None,
        expected_sla: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if hr_action_required:
            merged_details["hr_action_required"] = hr_action_required
        if expected_sla:
            merged_details["expected_sla"] = expected_sla
        super().__init__(
            message=message,
            error_code="AUTHZ_004",
            status_code=403,
            details=merged_details,
        )