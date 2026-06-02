"""
Audit log and tool log service.

Purpose:
- Business logic for creating audit logs and tool logs
- Called by other services: claim_service, leave_service, employee_service, auth_service
- Validates and enriches log data before storing
- Provides query methods for audit trails and tool logs

Pattern:
Route/Service → AuditLogService → AuditLogRepository / ToolLogRepository → MongoDB

Important:
- AI must never directly write logs.
- Backend tools/services should call this service.
- Audit logs are append-only.
- Tool logs can be created first and completed later.
- Do not store passwords, OTPs, tokens, raw payroll data, or bank details.
"""

from __future__ import annotations

from datetime import datetime as DateTime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.app.models.audit_log_model import (
    AuditActionCategory,
    AuditActor,
    AuditLog,
    AuditSensitivity,
    AuditSource,
    AuditStatus,
    AuditTarget,
    RequestSnapshot,
    ToolInputCategory,
    ToolLog,
    ToolLogStatus,
    ToolOutputCategory,
    utc_now,
)
from backend.app.repositories.audit_log_repository import (
    AuditLogRepository,
    ToolLogRepository,
)


class AuditLogService:
    """
    Service for audit logging and tool logging.

    Responsibilities:
    - Create safe audit logs
    - Create and complete tool logs
    - Query audit/tool logs with filters
    - Get audit/tool statistics
    """

    def __init__(
        self,
        audit_repo: AuditLogRepository,
        tool_repo: ToolLogRepository,
    ):
        self.audit_repo = audit_repo
        self.tool_repo = tool_repo

    # -------------------------
    # Internal helpers
    # -------------------------

    def _normalize_company_id(self, company_id: Optional[str] = "default") -> str:
        """
        Normalize company_id.
        """
        if not company_id:
            return "default"

        company_id = str(company_id).strip().lower()

        if not company_id:
            return "default"

        if not company_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "company_id can contain only letters, numbers, hyphen, and underscore"
            )

        return company_id

    def _enum_value(self, value: Any) -> Any:
        """
        Return enum value if value is Enum-like, otherwise return same value.
        """
        if hasattr(value, "value"):
            return value.value

        return value

    def _safe_dict(
        self,
        value: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Normalize optional dict to empty dict.
        """
        return value or {}

    def _resolve_company_id(
        self,
        company_id: Optional[str],
        target: Optional[AuditTarget] = None,
    ) -> str:
        """
        Resolve company_id from explicit value or target.
        """
        if company_id:
            return self._normalize_company_id(company_id)

        if target and target.company_id:
            return self._normalize_company_id(target.company_id)

        return "default"

    def _ensure_datetime_utc(self, value: Optional[DateTime]) -> Optional[DateTime]:
        """
        Ensure datetime is timezone-aware UTC.

        Handles MongoDB values that may come back as naive datetimes.
        """
        if value is None:
            return None

        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)

    def _calculate_latency_ms(
        self,
        started_at: Optional[DateTime],
        completed_at: DateTime,
    ) -> int:
        """
        Calculate latency in milliseconds safely.
        """
        if not started_at:
            return 0

        started = self._ensure_datetime_utc(started_at)
        completed = self._ensure_datetime_utc(completed_at)

        if not started or not completed:
            return 0

        latency = int((completed - started).total_seconds() * 1000)

        return max(0, latency)

    # -------------------------
    # Create audit log
    # -------------------------

    async def log_action(
        self,
        actor: AuditActor,
        target: AuditTarget,
        category: AuditActionCategory,
        action: str,
        status: AuditStatus = AuditStatus.SUCCESS,
        sensitivity: AuditSensitivity = AuditSensitivity.MEDIUM,
        is_sensitive: bool = False,
        message: Optional[str] = None,
        reason: Optional[str] = None,
        redaction_note: Optional[str] = None,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        request: Optional[RequestSnapshot] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        source: AuditSource = AuditSource.LOCAL,
        external_hrms_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> str:
        """
        Create an audit log entry.

        This is the main function other services should call.

        Examples:
        - employee created
        - leave submitted
        - claim approved
        - claim payment completed
        - HRMS sync failed
        """
        resolved_company_id = self._resolve_company_id(company_id, target)

        audit_log = AuditLog(
            company_id=resolved_company_id,
            actor=actor,
            target=target,
            category=category,
            action=action,
            status=status,
            sensitivity=sensitivity,
            is_sensitive=is_sensitive,
            message=message,
            reason=reason,
            redaction_note=redaction_note,
            before=before,
            after=after,
            extra_metadata=self._safe_dict(extra_metadata),
            request=request,
            error_code=error_code,
            error_message=error_message,
            source=source,
            external_hrms_id=external_hrms_id,
            created_at=utc_now(),
        )

        log_data = audit_log.model_dump(exclude_none=False)
        return await self.audit_repo.create(log_data)

    async def log_success(
        self,
        actor: AuditActor,
        target: AuditTarget,
        category: AuditActionCategory,
        action: str,
        message: Optional[str] = None,
        sensitivity: AuditSensitivity = AuditSensitivity.MEDIUM,
        extra_metadata: Optional[Dict[str, Any]] = None,
        company_id: Optional[str] = None,
    ) -> str:
        """
        Convenience method for successful action logs.
        """
        return await self.log_action(
            actor=actor,
            target=target,
            category=category,
            action=action,
            status=AuditStatus.SUCCESS,
            sensitivity=sensitivity,
            message=message,
            extra_metadata=extra_metadata,
            company_id=company_id,
        )

    async def log_failure(
        self,
        actor: AuditActor,
        target: AuditTarget,
        category: AuditActionCategory,
        action: str,
        error_message: str,
        error_code: Optional[str] = None,
        reason: Optional[str] = None,
        sensitivity: AuditSensitivity = AuditSensitivity.MEDIUM,
        extra_metadata: Optional[Dict[str, Any]] = None,
        company_id: Optional[str] = None,
    ) -> str:
        """
        Convenience method for failed action logs.
        """
        return await self.log_action(
            actor=actor,
            target=target,
            category=category,
            action=action,
            status=AuditStatus.FAILED,
            sensitivity=sensitivity,
            reason=reason,
            error_code=error_code,
            error_message=error_message,
            extra_metadata=extra_metadata,
            company_id=company_id,
        )

    async def log_denied(
        self,
        actor: AuditActor,
        target: AuditTarget,
        category: AuditActionCategory,
        action: str,
        reason: str,
        sensitivity: AuditSensitivity = AuditSensitivity.HIGH,
        extra_metadata: Optional[Dict[str, Any]] = None,
        company_id: Optional[str] = None,
    ) -> str:
        """
        Convenience method for denied/blocked action logs.
        """
        return await self.log_action(
            actor=actor,
            target=target,
            category=category,
            action=action,
            status=AuditStatus.DENIED,
            sensitivity=sensitivity,
            is_sensitive=True,
            reason=reason,
            extra_metadata=extra_metadata,
            company_id=company_id,
        )

    # -------------------------
    # Tool logs
    # -------------------------

    async def log_tool_call(
        self,
        tool_name: str,
        actor: AuditActor,
        tool_category: AuditActionCategory = AuditActionCategory.AI_TOOL,
        status: ToolLogStatus = ToolLogStatus.STARTED,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        input_category: ToolInputCategory = ToolInputCategory.UNKNOWN,
        output_category: ToolOutputCategory = ToolOutputCategory.UNKNOWN,
        input_summary: Optional[str] = None,
        output_summary: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        required_confirmation: bool = False,
        confirmed_by_user: bool = False,
        blocked_reason: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        is_sensitive: bool = False,
        company_id: Optional[str] = None,
    ) -> str:
        """
        Create a tool log entry for backend/AI tool execution.

        For future AI tools:
        - log started call before tool executes
        - complete it using complete_tool_call()
        """
        resolved_company_id = self._normalize_company_id(company_id)

        tool_log = ToolLog(
            company_id=resolved_company_id,
            tool_name=tool_name,
            tool_category=tool_category,
            status=status,
            actor=actor,
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            input_category=input_category,
            output_category=output_category,
            input_summary=input_summary,
            output_summary=output_summary,
            extra_metadata=self._safe_dict(extra_metadata),
            started_at=utc_now(),
            completed_at=None,
            latency_ms=None,
            error_code=error_code,
            error_message=error_message,
            required_confirmation=required_confirmation,
            confirmed_by_user=confirmed_by_user,
            blocked_reason=blocked_reason,
            is_sensitive=is_sensitive,
            created_at=utc_now(),
        )

        log_data = tool_log.model_dump(exclude_none=False)
        return await self.tool_repo.create(log_data)

    async def complete_tool_call(
        self,
        log_id: str,
        status: ToolLogStatus,
        output_summary: Optional[str] = None,
        output_category: Optional[ToolOutputCategory] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        blocked_reason: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        company_id: Optional[str] = None,
    ) -> bool:
        """
        Update tool log with completion details.

        Allowed final statuses:
        - success
        - failed
        - blocked
        - timeout
        """
        tool_log = await self.tool_repo.find_by_id(
            log_id=log_id,
            company_id=company_id,
        )

        if not tool_log:
            return False

        completed_at = utc_now()
        started_at = tool_log.get("started_at")
        latency_ms = self._calculate_latency_ms(started_at, completed_at)

        return await self.tool_repo.update_completion(
            log_id=log_id,
            status=self._enum_value(status),
            completed_at=completed_at,
            latency_ms=latency_ms,
            output_summary=output_summary,
            output_category=self._enum_value(output_category) if output_category else None,
            error_code=error_code,
            error_message=error_message,
            blocked_reason=blocked_reason,
            extra_metadata=extra_metadata,
        )

    async def log_blocked_tool_call(
        self,
        tool_name: str,
        actor: AuditActor,
        blocked_reason: str,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        input_summary: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        company_id: Optional[str] = None,
    ) -> str:
        """
        Convenience method for blocked tool calls.

        Useful when AI/tool attempted a sensitive action without permission/confirmation.
        """
        return await self.log_tool_call(
            tool_name=tool_name,
            actor=actor,
            status=ToolLogStatus.BLOCKED,
            session_id=session_id,
            conversation_id=conversation_id,
            input_summary=input_summary,
            output_category=ToolOutputCategory.ERROR,
            blocked_reason=blocked_reason,
            extra_metadata=extra_metadata,
            required_confirmation=True,
            confirmed_by_user=False,
            is_sensitive=True,
            company_id=company_id,
        )

    # -------------------------
    # Query audit logs
    # -------------------------

    async def get_audit_trail(
        self,
        company_id: str = "default",
        actor_id: Optional[str] = None,
        actor_type: Optional[str] = None,
        actor_role: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        employee_id: Optional[str] = None,
        category: Optional[str] = None,
        action: Optional[str] = None,
        status: Optional[str] = None,
        sensitivity: Optional[str] = None,
        is_sensitive: Optional[bool] = None,
        source: Optional[str] = None,
        external_hrms_id: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        search: Optional[str] = None,
        limit: int = 100,
        skip: int = 0,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Query audit trail with filters.

        Returns:
            (logs, total)
        """
        logs = await self.audit_repo.list_logs(
            company_id=company_id,
            actor_id=actor_id,
            actor_type=actor_type,
            actor_role=actor_role,
            category=category,
            action=action,
            status=status,
            sensitivity=sensitivity,
            is_sensitive=is_sensitive,
            target_type=target_type,
            target_id=target_id,
            employee_id=employee_id,
            source=source,
            external_hrms_id=external_hrms_id,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            start_date=start_date,
            end_date=end_date,
            search=search,
            skip=skip,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        total = await self.audit_repo.count_logs(
            company_id=company_id,
            actor_id=actor_id,
            actor_type=actor_type,
            actor_role=actor_role,
            category=category,
            action=action,
            status=status,
            sensitivity=sensitivity,
            is_sensitive=is_sensitive,
            target_type=target_type,
            target_id=target_id,
            employee_id=employee_id,
            source=source,
            external_hrms_id=external_hrms_id,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            start_date=start_date,
            end_date=end_date,
            search=search,
        )

        return logs, total

    async def get_employee_audit_trail(
        self,
        employee_id: str,
        company_id: str = "default",
        category: Optional[str] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get all audit logs related to an employee.

        This checks:
        - target.employee_id
        - actor.actor_id
        """
        target_logs, _ = await self.get_audit_trail(
            company_id=company_id,
            employee_id=employee_id,
            category=category,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip,
        )

        actor_logs, _ = await self.get_audit_trail(
            company_id=company_id,
            actor_id=employee_id,
            category=category,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip,
        )

        merged: Dict[str, Dict[str, Any]] = {}

        for log in target_logs + actor_logs:
            log_id = log.get("id") or log.get("_id")
            if log_id:
                merged[str(log_id)] = log

        logs = sorted(
            merged.values(),
            key=lambda item: item.get("created_at"),
            reverse=True,
        )

        return logs[:limit], len(merged)

    async def get_sensitive_logs(
        self,
        company_id: str = "default",
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        category: Optional[str] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get logs marked as sensitive.
        """
        return await self.get_audit_trail(
            company_id=company_id,
            category=category,
            is_sensitive=True,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip,
        )

    async def get_audit_by_id(
        self,
        log_id: str,
        company_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get audit log by ID.
        """
        return await self.audit_repo.find_by_id(
            log_id=log_id,
            company_id=company_id,
        )

    # -------------------------
    # Query tool logs
    # -------------------------

    async def get_tool_logs(
        self,
        company_id: str = "default",
        tool_name: Optional[str] = None,
        status: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_type: Optional[str] = None,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        input_category: Optional[str] = None,
        output_category: Optional[str] = None,
        is_sensitive: Optional[bool] = None,
        required_confirmation: Optional[bool] = None,
        confirmed_by_user: Optional[bool] = None,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        search: Optional[str] = None,
        limit: int = 100,
        skip: int = 0,
        sort_by: str = "started_at",
        sort_order: str = "desc",
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Query tool logs with filters.

        Returns:
            (logs, total)
        """
        logs = await self.tool_repo.list_tool_logs(
            company_id=company_id,
            tool_name=tool_name,
            status=status,
            actor_id=actor_id,
            actor_type=actor_type,
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            input_category=input_category,
            output_category=output_category,
            is_sensitive=is_sensitive,
            required_confirmation=required_confirmation,
            confirmed_by_user=confirmed_by_user,
            start_date=start_date,
            end_date=end_date,
            search=search,
            skip=skip,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        total = await self.tool_repo.count_tool_logs(
            company_id=company_id,
            tool_name=tool_name,
            status=status,
            actor_id=actor_id,
            actor_type=actor_type,
            session_id=session_id,
            conversation_id=conversation_id,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            input_category=input_category,
            output_category=output_category,
            is_sensitive=is_sensitive,
            required_confirmation=required_confirmation,
            confirmed_by_user=confirmed_by_user,
            start_date=start_date,
            end_date=end_date,
            search=search,
        )

        return logs, total

    async def get_tool_log_by_id(
        self,
        log_id: str,
        company_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get tool log by ID.
        """
        return await self.tool_repo.find_by_id(
            log_id=log_id,
            company_id=company_id,
        )

    async def get_sensitive_tool_logs(
        self,
        company_id: str = "default",
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get sensitive tool logs.
        """
        return await self.get_tool_logs(
            company_id=company_id,
            is_sensitive=True,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            skip=skip,
        )

    # -------------------------
    # Statistics
    # -------------------------

    async def get_audit_statistics(
        self,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Get audit log statistics for dashboard.
        """
        return await self.audit_repo.get_statistics(
            start_date=start_date,
            end_date=end_date,
            company_id=company_id,
        )

    async def get_tool_statistics(
        self,
        start_date: Optional[DateTime] = None,
        end_date: Optional[DateTime] = None,
        company_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Get tool log statistics for dashboard.
        """
        return await self.tool_repo.get_statistics(
            start_date=start_date,
            end_date=end_date,
            company_id=company_id,
        )