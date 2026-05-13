from .base import BaseAppException
from .auth_exceptions import (
    AuthenticationException,
    ExpiredTokenException,
    InvalidTokenException,
    MFAValidationException,
)
from .authorization_exceptions import (
    AuthorizationException,
    HRApprovalRequiredException,
    PermissionDeniedException,
    RoleRestrictionException,
    SensitiveActionException,
)
from .ai_exceptions import (
    AIException,
    ContextOverflowException,
    HallucinationDetectedException,
    JailbreakAttemptException,
    LLMUnavailableException,
    LowConfidenceException,
    PromptInjectionException,
)
from .rag_exceptions import (
    EmbeddingGenerationException,
    PolicyNotFoundException,
    RAGException,
    VectorDBException,
)
from .leave_exceptions import (
    InsufficientLeaveBalanceException,
    LeaveException,
    LeaveOverlapException,
    RestrictedLeaveTypeException,
)
from .payroll_exceptions import (
    PayrollException,
    PayslipNotFoundException,
    SalaryMismatchException,
    UnauthorizedPayrollAccessException,
)
from .security_exceptions import (
    PIILeakageException,
    RateLimitExceededException,
    SecurityException,
    SQLInjectionException,
    SuspiciousActivityException,
)
from .infrastructure_exceptions import (
    APITimeoutException,
    DatabaseConnectionException,
    DuplicateRecordException,
    InfrastructureException,
    ServiceUnavailableException,
)

__all__ = [
    "BaseAppException",
    "AuthenticationException",
    "InvalidTokenException",
    "ExpiredTokenException",
    "MFAValidationException",
    "AuthorizationException",
    "PermissionDeniedException",
    "RoleRestrictionException",
    "SensitiveActionException",
    "HRApprovalRequiredException",
    "AIException",
    "PromptInjectionException",
    "JailbreakAttemptException",
    "LowConfidenceException",
    "HallucinationDetectedException",
    "ContextOverflowException",
    "LLMUnavailableException",
    "RAGException",
    "PolicyNotFoundException",
    "VectorDBException",
    "EmbeddingGenerationException",
    "LeaveException",
    "InsufficientLeaveBalanceException",
    "LeaveOverlapException",
    "RestrictedLeaveTypeException",
    "PayrollException",
    "PayslipNotFoundException",
    "UnauthorizedPayrollAccessException",
    "SalaryMismatchException",
    "SecurityException",
    "RateLimitExceededException",
    "PIILeakageException",
    "SuspiciousActivityException",
    "SQLInjectionException",
    "InfrastructureException",
    "DatabaseConnectionException",
    "DuplicateRecordException",
    "ServiceUnavailableException",
    "APITimeoutException",
]