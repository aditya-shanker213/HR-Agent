"""
Audit and tool log models.

Purpose:
- Store important backend actions for compliance, debugging, and production safety.
- Store AI/tool calls separately so future LangGraph/MCP tools can be traced.
- AI must never directly write logs. Tools/services should call audit/tool log service.

Used by:
- Auth module
- Employee module
- Leave module
- Claim module
- Payroll module
- HRMS sync module
- Future AI tools
- Future LangGraph agent

Safety:
- Never store passwords, OTPs, tokens, API keys, or full payroll/salary/bank data.
- Use is_sensitive=True for high-risk actions.
- Use redaction_note to explain removed sensitive data.
- Validators block accidental secret storage in before/after/extra_metadata.
"""

from __future__ import annotations

from datetime import datetime as DateTime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


# -------------------------
# Shared helpers
# -------------------------


FORBIDDEN_LOG_KEYS = {
    "password",
    "hashed_password",
    "old_password",
    "new_password",
    "confirm_password",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "jwt",
    "bearer",
    "authorization",
    "auth_header",
    "secret",
    "client_secret",
    "api_key",
    "private_key",
    "public_key",
    "otp",
    "otp_code",
    "pin",
    "mfa_code",
    "verification_code",
    "reset_code",
    "ssn",
    "aadhaar",
    "aadhaar_number",
    "pan",
    "pan_number",
    "salary_amount",
    "basic_salary",
    "gross_salary",
    "net_salary",
    "ctc",
    "payroll_amount",
    "salary_slip",
    "bank_account",
    "account_number",
    "ifsc",
    "iban",
    "credit_card",
    "debit_card",
    "card_number",
    "cvv",
}


def utc_now() -> DateTime:
    """
    Return timezone-aware UTC datetime for all logs.

    Why:
    - Production logs may come from web, AI tools, n8n, HRMS, and background scripts.
    - Timezone-aware UTC avoids confusion when comparing events across systems.
    """
    return DateTime.now(timezone.utc)


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    """
    Strip optional text values.
    Empty string becomes None.
    """
    if value is None:
        return None

    value = str(value).strip()
    return value or None


def normalize_required_text(value: str, field_name: str) -> str:
    """
    Strip required text values.
    Empty string is not allowed.
    """
    value = str(value).strip()

    if not value:
        raise ValueError(f"{field_name} cannot be empty")

    return value


def normalize_company_id(value: Optional[str]) -> str:
    """
    Normalize company_id.

    Rules:
    - default if missing
    - lowercase
    - only letters, numbers, hyphen, underscore
    """
    if value is None:
        return "default"

    value = str(value).strip().lower()

    if not value:
        return "default"

    if not value.replace("_", "").replace("-", "").isalnum():
        raise ValueError(
            "company_id can contain only letters, numbers, hyphen, and underscore"
        )

    return value


def _contains_forbidden_key(value: Any, path: str = "") -> Optional[str]:
    """
    Recursively scan dict/list structures for forbidden sensitive keys.

    Returns:
        first forbidden path found, or None
    """
    if isinstance(value, dict):
        for key, nested_value in value.items():
            key_str = str(key).strip().lower()
            current_path = f"{path}.{key_str}" if path else key_str

            if key_str in FORBIDDEN_LOG_KEYS:
                return current_path

            found = _contains_forbidden_key(nested_value, current_path)
            if found:
                return found

    elif isinstance(value, list):
        for index, item in enumerate(value):
            current_path = f"{path}[{index}]"
            found = _contains_forbidden_key(item, current_path)
            if found:
                return found

    return None


def validate_safe_log_payload(value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """
    Validate that log payload does not contain obvious sensitive fields.
    """
    if value is None:
        return value

    found_path = _contains_forbidden_key(value)

    if found_path:
        raise ValueError(
            f"Cannot store sensitive field '{found_path}' in logs. "
            "Redact it before logging and use redaction_note."
        )

    return value


# -------------------------
# Enums
# -------------------------


class AuditActorType(str, Enum):
    """
    Who performed the action.
    """

    USER = "user"
    EMPLOYEE = "employee"
    MANAGER = "manager"
    HR = "hr"
    ADMIN = "admin"
    FINANCE = "finance"
    SYSTEM = "system"
    AI_AGENT = "ai_agent"
    N8N = "n8n"
    HRMS = "hrms"
    SCRIPT = "script"


class AuditActionCategory(str, Enum):
    """
    High-level action category.
    """

    AUTH = "auth"
    EMPLOYEE = "employee"
    MASTER_DATA = "master_data"
    COMPANY_SETTINGS = "company_settings"
    LEAVE = "leave"
    CLAIM = "claim"
    PAYROLL = "payroll"
    POLICY = "policy"
    AI_TOOL = "ai_tool"
    HRMS_SYNC = "hrms_sync"
    NOTIFICATION = "notification"
    SYSTEM = "system"


class AuditActionType(str, Enum):
    """
    Common action names.

    Services can still store custom action strings if needed,
    but these values should cover most workflows.
    """

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    DEACTIVATED = "deactivated"
    ACTIVATED = "activated"
    RESTORED = "restored"

    # Auth actions
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    OTP_REQUESTED = "otp_requested"
    OTP_VERIFIED = "otp_verified"
    OTP_FAILED = "otp_failed"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_RESET_COMPLETED = "password_reset_completed"
    ACCOUNT_ACTIVATION_REQUESTED = "account_activation_requested"
    ACCOUNT_ACTIVATED = "account_activated"

    # Workflow actions
    DRAFT_CREATED = "draft_created"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    WITHDRAWN = "withdrawn"
    SENT_BACK = "sent_back"
    RESUBMITTED = "resubmitted"

    # Payment actions
    PAYMENT_STARTED = "payment_started"
    PAYMENT_COMPLETED = "payment_completed"
    PAYMENT_FAILED = "payment_failed"

    # Data access actions
    VIEWED = "viewed"
    DOWNLOADED = "downloaded"
    EXPORTED = "exported"
    SEARCHED = "searched"

    # Tool actions
    TOOL_CALLED = "tool_called"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    TOOL_BLOCKED = "tool_blocked"

    # HRMS sync actions
    IMPORTED_FROM_HRMS = "imported_from_hrms"
    SYNCED_TO_HRMS = "synced_to_hrms"
    HRMS_SYNC_FAILED = "hrms_sync_failed"
    HRMS_WRITE_ATTEMPTED = "hrms_write_attempted"
    HRMS_WRITE_BLOCKED = "hrms_write_blocked"


class AuditStatus(str, Enum):
    """
    Result of the logged action.
    """

    SUCCESS = "success"
    FAILED = "failed"
    DENIED = "denied"
    PENDING = "pending"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class AuditSensitivity(str, Enum):
    """
    Sensitivity level of the logged action.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AuditSource(str, Enum):
    """
    Where the action came from.
    """

    LOCAL = "local"
    WEB = "web"
    MOBILE = "mobile"
    VOICE = "voice"
    AI_AGENT = "ai_agent"
    HRMS = "hrms"
    IMPORTED = "imported"
    N8N = "n8n"
    SCRIPT = "script"
    SYSTEM = "system"


class ToolLogStatus(str, Enum):
    """
    Status of AI/backend tool execution.
    """

    STARTED = "started"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"


class ToolInputCategory(str, Enum):
    """
    What kind of input the tool received.

    Do not store full sensitive payroll/claim documents in logs.
    Store category + safe summary + safe metadata only.
    """

    GENERAL = "general"
    EMPLOYEE_DATA = "employee_data"
    LEAVE_DATA = "leave_data"
    CLAIM_DATA = "claim_data"
    PAYROLL_DATA = "payroll_data"
    POLICY_QUERY = "policy_query"
    AUTH_DATA = "auth_data"
    HRMS_DATA = "hrms_data"
    UNKNOWN = "unknown"


class ToolOutputCategory(str, Enum):
    """
    What kind of output the tool returned.
    """

    GENERAL = "general"
    EMPLOYEE_SUMMARY = "employee_summary"
    LEAVE_RESULT = "leave_result"
    CLAIM_RESULT = "claim_result"
    PAYROLL_SUMMARY = "payroll_summary"
    POLICY_CONTEXT = "policy_context"
    HRMS_RESULT = "hrms_result"
    ERROR = "error"
    UNKNOWN = "unknown"


# -------------------------
# Nested models
# -------------------------


class AuditActor(BaseModel):
    """
    Snapshot of the actor who performed the action.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
        use_enum_values=True,
    )

    actor_id: Optional[str] = Field(
        default=None,
        description="User ID / employee ID / system identifier",
    )

    actor_type: AuditActorType = Field(
        default=AuditActorType.SYSTEM,
        description="Type of actor who performed the action",
    )

    actor_role: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Role at action time: employee, manager, hr, admin, finance",
    )

    actor_name: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Display name of actor at action time",
    )

    actor_email: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Actor email if available",
    )

    @field_validator("actor_id", "actor_role", "actor_name", "actor_email")
    @classmethod
    def clean_optional_actor_text(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


class AuditTarget(BaseModel):
    """
    Entity affected by the action.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    target_type: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Entity type: employee, leave_request, claim, payroll, policy_document",
    )

    target_id: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Primary ID of affected entity",
    )

    target_display: Optional[str] = Field(
        default=None,
        max_length=300,
        description="Human-readable label for affected entity",
    )

    employee_id: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Employee ID related to this action, if applicable",
    )

    company_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Company/tenant ID",
    )

    @field_validator("target_type")
    @classmethod
    def clean_required_target_type(cls, value: str) -> str:
        return normalize_required_text(value, "target_type")

    @field_validator("target_id", "target_display", "employee_id")
    @classmethod
    def clean_optional_target_text(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("company_id")
    @classmethod
    def clean_company_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        return normalize_company_id(value)


class RequestSnapshot(BaseModel):
    """
    Safe request metadata.

    Do not store raw tokens, passwords, OTP, salary slip content, or full files.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
        use_enum_values=True,
    )

    request_id: Optional[str] = Field(default=None, max_length=150)
    correlation_id: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Correlation ID for distributed tracing",
    )
    trace_id: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Trace ID for observability systems",
    )
    ip_address: Optional[str] = Field(default=None, max_length=100)
    user_agent: Optional[str] = Field(default=None, max_length=500)
    method: Optional[str] = Field(default=None, max_length=20)
    path: Optional[str] = Field(default=None, max_length=500)
    source: Optional[AuditSource] = Field(
        default=None,
        description="web, mobile, voice, ai_agent, n8n, hrms_sync, script",
    )

    @field_validator(
        "request_id",
        "correlation_id",
        "trace_id",
        "ip_address",
        "user_agent",
        "method",
        "path",
    )
    @classmethod
    def clean_optional_request_text(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)


# -------------------------
# Main audit log model
# -------------------------


class AuditLog(BaseModel):
    """
    Audit log document for audit_logs collection.

    Append-only design:
    - Create new log for every important action.
    - Do not update old audit logs except exceptional maintenance.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True,
        extra="forbid",
    )

    # Versioning
    schema_version: int = Field(
        default=1,
        ge=1,
        description="Audit log schema version for future migrations",
    )

    # Company/tenant ID at top level for fast filtering
    company_id: str = Field(
        default="default",
        min_length=2,
        max_length=100,
        description="Company/tenant ID for multi-tenant support",
    )

    # Actor and target
    actor: AuditActor = Field(
        default_factory=AuditActor,
        description="Who performed the action",
    )

    target: AuditTarget = Field(
        ...,
        description="Entity affected by this action",
    )

    # Action
    category: AuditActionCategory = Field(
        ...,
        description="High-level action category",
    )

    action: str = Field(
        ...,
        min_length=2,
        max_length=150,
        description="Action name, can use AuditActionType values or custom action string",
    )

    status: AuditStatus = Field(
        default=AuditStatus.SUCCESS,
        description="Action result",
    )

    sensitivity: AuditSensitivity = Field(
        default=AuditSensitivity.MEDIUM,
        description="Sensitivity level of the event",
    )

    is_sensitive: bool = Field(
        default=False,
        description="Flag for high-risk actions requiring extra review",
    )

    # Description
    message: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Safe human-readable explanation",
    )

    reason: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Reason for approval/rejection/denial/failure",
    )

    redaction_note: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Note if sensitive data was redacted from this log",
    )

    # Change tracking
    before: Optional[dict[str, Any]] = Field(
        default=None,
        description="Safe before snapshot. Avoid storing sensitive full data.",
    )

    after: Optional[dict[str, Any]] = Field(
        default=None,
        description="Safe after snapshot. Avoid storing sensitive full data.",
    )

    extra_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra safe metadata for debugging/reporting",
    )

    # Request info
    request: Optional[RequestSnapshot] = Field(
        default=None,
        description="Safe HTTP/request metadata",
    )

    # Error info
    error_code: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Internal safe error code",
    )

    error_message: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Safe error message. Do not store secrets.",
    )

    # HRMS compatibility
    source: AuditSource = Field(
        default=AuditSource.LOCAL,
        description="local, web, mobile, voice, hrms, ai_agent, imported, n8n",
    )

    external_hrms_id: Optional[str] = Field(
        default=None,
        max_length=150,
        description="External HRMS reference ID if related",
    )

    # Timestamps
    created_at: DateTime = Field(
        default_factory=utc_now,
        description="When this audit log was created",
    )

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: Optional[str]) -> str:
        return normalize_company_id(value)

    @field_validator("action")
    @classmethod
    def clean_required_action(cls, value: str) -> str:
        return normalize_required_text(value, "action")

    @field_validator(
        "message",
        "reason",
        "redaction_note",
        "error_code",
        "error_message",
        "external_hrms_id",
    )
    @classmethod
    def clean_optional_strings(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("before", "after", "extra_metadata")
    @classmethod
    def validate_no_secrets(cls, value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """
        Ensure no secrets are accidentally stored in logs.
        """
        return validate_safe_log_payload(value)

    @model_validator(mode="after")
    def validate_sensitivity_rules(self):
        """
        High/critical sensitivity should be explicitly marked.
        Also keep target.company_id synced with top-level company_id.
        """
        if self.sensitivity in {
            AuditSensitivity.HIGH,
            AuditSensitivity.CRITICAL,
            "high",
            "critical",
        }:
            self.is_sensitive = True

        if self.target.company_id is None:
            self.target.company_id = self.company_id

        return self


# -------------------------
# Tool log model
# -------------------------


class ToolLog(BaseModel):
    """
    Tool log document for tool_logs collection.

    Mainly for future AI/LangGraph/MCP tools.

    Examples:
    - AI calls get_my_leave_balance
    - AI calls submit_claim after user confirmation
    - AI calls search_policy_docs
    - AI calls get_salary_summary after step-up auth

    Store safe metadata, not raw sensitive payloads.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True,
        extra="forbid",
    )

    # Versioning
    schema_version: int = Field(
        default=1,
        ge=1,
        description="Tool log schema version for future migrations",
    )

    # Company/tenant ID at top level
    company_id: str = Field(
        default="default",
        min_length=2,
        max_length=100,
        description="Company/tenant ID for multi-tenant support",
    )

    # Tool identity
    tool_name: str = Field(
        ...,
        min_length=2,
        max_length=150,
        description="Tool/function name",
    )

    tool_category: AuditActionCategory = Field(
        default=AuditActionCategory.AI_TOOL,
        description="Tool category",
    )

    status: ToolLogStatus = Field(
        default=ToolLogStatus.STARTED,
        description="Tool execution status",
    )

    # Actor/session
    actor: AuditActor = Field(
        default_factory=AuditActor,
        description="Who/what triggered the tool",
    )

    session_id: Optional[str] = Field(
        default=None,
        max_length=150,
        description="AI/chat/voice session ID if available",
    )

    conversation_id: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Conversation ID if available",
    )

    request_id: Optional[str] = Field(
        default=None,
        max_length=150,
        description="HTTP request ID or internal trace ID",
    )

    correlation_id: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Correlation ID for distributed tracing",
    )

    trace_id: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Trace ID for observability systems",
    )

    # Input/output category only
    input_category: ToolInputCategory = Field(
        default=ToolInputCategory.UNKNOWN,
        description="Category of tool input",
    )

    output_category: ToolOutputCategory = Field(
        default=ToolOutputCategory.UNKNOWN,
        description="Category of tool output",
    )

    # Safe metadata
    input_summary: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Safe summary of input. Do not store raw sensitive data.",
    )

    output_summary: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Safe summary of output. Do not store raw sensitive data.",
    )

    extra_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra safe metadata like claim_id, leave_id, policy_doc_id",
    )

    # Timing
    started_at: DateTime = Field(
        default_factory=utc_now,
        description="Tool execution start time",
    )

    completed_at: Optional[DateTime] = Field(
        default=None,
        description="Tool execution completion time",
    )

    latency_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Execution latency in milliseconds",
    )

    # Error
    error_code: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Safe internal error code",
    )

    error_message: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Safe error message",
    )

    # Safety / confirmation
    required_confirmation: bool = Field(
        default=False,
        description="Whether this tool required user confirmation",
    )

    confirmed_by_user: bool = Field(
        default=False,
        description="Whether user confirmation was received",
    )

    blocked_reason: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Why tool was blocked, if blocked",
    )

    is_sensitive: bool = Field(
        default=False,
        description="Flag for sensitive tool calls requiring review",
    )

    created_at: DateTime = Field(
        default_factory=utc_now,
        description="When log document was created",
    )

    @field_validator("company_id")
    @classmethod
    def validate_company_id(cls, value: Optional[str]) -> str:
        return normalize_company_id(value)

    @field_validator("tool_name")
    @classmethod
    def clean_required_tool_name(cls, value: str) -> str:
        return normalize_required_text(value, "tool_name")

    @field_validator(
        "session_id",
        "conversation_id",
        "request_id",
        "correlation_id",
        "trace_id",
        "input_summary",
        "output_summary",
        "error_code",
        "error_message",
        "blocked_reason",
    )
    @classmethod
    def clean_optional_tool_text(cls, value: Optional[str]) -> Optional[str]:
        return normalize_optional_text(value)

    @field_validator("extra_metadata")
    @classmethod
    def validate_no_secrets_in_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        """
        Ensure no secrets in tool log metadata.
        """
        validate_safe_log_payload(value)
        return value

    @model_validator(mode="after")
    def validate_tool_status_fields(self):
        """
        Validate tool log timing/status consistency.
        """
        if self.status in {
            ToolLogStatus.SUCCESS,
            ToolLogStatus.FAILED,
            ToolLogStatus.BLOCKED,
            ToolLogStatus.TIMEOUT,
            "success",
            "failed",
            "blocked",
            "timeout",
        }:
            if self.completed_at is None:
                self.completed_at = utc_now()

        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be before started_at")

        if self.status in {ToolLogStatus.FAILED, "failed"}:
            if not self.error_code and not self.error_message:
                raise ValueError(
                    "error_code or error_message is required when tool status=failed"
                )

        if self.status in {ToolLogStatus.BLOCKED, "blocked"}:
            if not self.blocked_reason:
                raise ValueError("blocked_reason is required when tool status=blocked")

        return self


# -------------------------
# Response models for API/dashboard
# -------------------------


class AuditLogSummary(BaseModel):
    """
    Summary model for audit log list endpoints.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        from_attributes=True,
    )

    id: Optional[str] = None
    schema_version: int = 1
    company_id: str = "default"

    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    actor_type: str

    category: str
    action: str
    status: str

    target_type: str
    target_id: Optional[str] = None
    target_display: Optional[str] = None

    message: Optional[str] = None
    sensitivity: str
    is_sensitive: bool

    source: str = "local"
    created_at: DateTime


class AuditLogDetail(BaseModel):
    """
    Detailed audit log for single record view.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        from_attributes=True,
    )

    id: Optional[str] = None
    schema_version: int = 1
    company_id: str = "default"

    actor: AuditActor
    target: AuditTarget

    category: str
    action: str
    status: str
    sensitivity: str
    is_sensitive: bool

    message: Optional[str] = None
    reason: Optional[str] = None
    redaction_note: Optional[str] = None

    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    extra_metadata: dict[str, Any] = Field(default_factory=dict)

    request: Optional[RequestSnapshot] = None

    error_code: Optional[str] = None
    error_message: Optional[str] = None

    source: str = "local"
    external_hrms_id: Optional[str] = None

    created_at: DateTime


class ToolLogSummary(BaseModel):
    """
    Summary model for tool log list endpoints.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        from_attributes=True,
    )

    id: Optional[str] = None
    schema_version: int = 1
    company_id: str = "default"

    tool_name: str
    status: str

    actor_id: Optional[str] = None
    actor_name: Optional[str] = None

    session_id: Optional[str] = None
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None

    input_category: str
    output_category: str

    latency_ms: Optional[int] = None

    required_confirmation: bool
    confirmed_by_user: bool
    is_sensitive: bool

    started_at: DateTime
    completed_at: Optional[DateTime] = None


class ToolLogDetail(BaseModel):
    """
    Detailed tool log for single record view.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        from_attributes=True,
    )

    id: Optional[str] = None
    schema_version: int = 1
    company_id: str = "default"

    tool_name: str
    tool_category: str
    status: str

    actor: AuditActor

    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None

    input_category: str
    output_category: str
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None

    extra_metadata: dict[str, Any] = Field(default_factory=dict)

    started_at: DateTime
    completed_at: Optional[DateTime] = None
    latency_ms: Optional[int] = None

    error_code: Optional[str] = None
    error_message: Optional[str] = None

    required_confirmation: bool
    confirmed_by_user: bool
    blocked_reason: Optional[str] = None
    is_sensitive: bool

    created_at: DateTime


class AuditLogStatistics(BaseModel):
    """
    Basic audit dashboard/statistics response.
    """

    model_config = ConfigDict(from_attributes=True)

    company_id: str = "default"

    total_logs: int = 0
    success_logs: int = 0
    failed_logs: int = 0
    denied_logs: int = 0
    blocked_logs: int = 0

    sensitive_logs: int = 0
    critical_logs: int = 0

    logs_by_category: dict[str, int] = Field(default_factory=dict)
    logs_by_action: dict[str, int] = Field(default_factory=dict)
    logs_by_actor_type: dict[str, int] = Field(default_factory=dict)
    logs_by_status: dict[str, int] = Field(default_factory=dict)


class ToolLogStatistics(BaseModel):
    """
    Basic tool dashboard/statistics response.
    """

    model_config = ConfigDict(from_attributes=True)

    company_id: str = "default"

    total_tool_calls: int = 0
    successful_tool_calls: int = 0
    failed_tool_calls: int = 0
    blocked_tool_calls: int = 0
    timeout_tool_calls: int = 0

    sensitive_tool_calls: int = 0
    confirmation_required_calls: int = 0

    average_latency_ms: Optional[float] = None

    calls_by_tool: dict[str, int] = Field(default_factory=dict)
    calls_by_status: dict[str, int] = Field(default_factory=dict)
    calls_by_input_category: dict[str, int] = Field(default_factory=dict)
    calls_by_output_category: dict[str, int] = Field(default_factory=dict)


# -------------------------
# Helper functions
# -------------------------


def build_system_actor(
    actor_id: str = "system",
    actor_type: AuditActorType = AuditActorType.SYSTEM,
) -> AuditActor:
    """
    Build a standard system actor.
    """
    return AuditActor(
        actor_id=actor_id,
        actor_type=actor_type,
        actor_role="system",
        actor_name="System",
    )


def build_hrms_actor(
    external_hrms_id: Optional[str] = None,
) -> AuditActor:
    """
    Build actor snapshot for HRMS sync/import actions.
    """
    return AuditActor(
        actor_id=external_hrms_id or "hrms",
        actor_type=AuditActorType.HRMS,
        actor_role="hrms",
        actor_name="HRMS",
    )


def build_ai_actor(
    agent_name: str = "HR AI Agent",
    session_id: Optional[str] = None,
) -> AuditActor:
    """
    Build actor snapshot for AI/tool actions.

    Note:
    AI should not directly write logs.
    Tool/service layer should create logs using this actor when needed.
    """
    return AuditActor(
        actor_id=session_id or "ai_agent",
        actor_type=AuditActorType.AI_AGENT,
        actor_role="ai_agent",
        actor_name=agent_name,
    )


def build_user_actor(
    current_user: dict[str, Any],
    default_actor_type: AuditActorType = AuditActorType.USER,
) -> AuditActor:
    """
    Build actor snapshot from current_user dict.

    Works with your existing auth dependency style where current_user is dict.
    """
    raw_role = current_user.get("role")

    if hasattr(raw_role, "value"):
        raw_role = raw_role.value

    return AuditActor(
        actor_id=str(
            current_user.get("_id")
            or current_user.get("id")
            or current_user.get("user_id")
            or current_user.get("employee_id")
            or ""
        )
        or None,
        actor_type=default_actor_type,
        actor_role=raw_role,
        actor_name=current_user.get("full_name")
        or current_user.get("name")
        or current_user.get("username"),
        actor_email=current_user.get("email"),
    )


def build_audit_target(
    target_type: str,
    target_id: Optional[str] = None,
    target_display: Optional[str] = None,
    employee_id: Optional[str] = None,
    company_id: Optional[str] = None,
) -> AuditTarget:
    """
    Quick helper to build AuditTarget.
    """
    return AuditTarget(
        target_type=target_type,
        target_id=target_id,
        target_display=target_display,
        employee_id=employee_id,
        company_id=company_id,
    )


def build_request_snapshot(
    request_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    method: Optional[str] = None,
    path: Optional[str] = None,
    source: Optional[AuditSource] = None,
) -> RequestSnapshot:
    """
    Quick helper to build safe request metadata.
    """
    return RequestSnapshot(
        request_id=request_id,
        correlation_id=correlation_id,
        trace_id=trace_id,
        ip_address=ip_address,
        user_agent=user_agent,
        method=method,
        path=path,
        source=source,
    )