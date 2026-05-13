from typing import Any

from .base import BaseAppException


class AIException(BaseAppException):
    def __init__(
        self,
        message: str,
        error_code: str = "AI_BASE",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            details=details,
        )


class PromptInjectionException(AIException):
    def __init__(
        self,
        message: str = "Input blocked due to detected prompt injection patterns.",
        blocked_pattern: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if blocked_pattern:
            merged_details["blocked_pattern"] = blocked_pattern
        super().__init__(
            message=message,
            error_code="AI_001",
            status_code=400,
            details=merged_details,
        )


class JailbreakAttemptException(AIException):
    def __init__(
        self,
        message: str = "Input blocked due to detected jailbreak or adversarial patterns.",
        blocked_pattern: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if blocked_pattern:
            merged_details["blocked_pattern"] = blocked_pattern
        super().__init__(
            message=message,
            error_code="AI_002",
            status_code=400,
            details=merged_details,
        )


class LowConfidenceException(AIException):
    def __init__(
        self,
        message: str = "Could not understand your request with enough confidence. Could you rephrase?",
        top_intent: str | None = None,
        confidence_score: float | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if top_intent:
            merged_details["top_intent"] = top_intent
        if confidence_score is not None:
            merged_details["confidence_score"] = confidence_score
        super().__init__(
            message=message,
            error_code="AI_003",
            status_code=422,
            details=merged_details,
        )


class HallucinationDetectedException(AIException):
    def __init__(
        self,
        message: str = "Generated response contained claims not grounded in the retrieved context.",
        ungrounded_claims: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if ungrounded_claims:
            merged_details["ungrounded_claims"] = ungrounded_claims
        super().__init__(
            message=message,
            error_code="AI_004",
            status_code=422,
            details=merged_details,
        )


class ContextOverflowException(AIException):
    def __init__(
        self,
        message: str = "The conversation context has exceeded the model's token limit.",
        current_tokens: int | None = None,
        max_tokens: int | None = None,
        largest_component: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if current_tokens is not None:
            merged_details["current_tokens"] = current_tokens
        if max_tokens is not None:
            merged_details["max_tokens"] = max_tokens
        if largest_component:
            merged_details["largest_component"] = largest_component
        super().__init__(
            message=message,
            error_code="AI_005",
            status_code=413,
            details=merged_details,
        )


class LLMUnavailableException(AIException):
    def __init__(
        self,
        message: str = "AI service is temporarily unavailable. Non-AI features remain accessible.",
        provider: str | None = None,
        retry_after_seconds: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if provider:
            merged_details["provider"] = provider
        if retry_after_seconds is not None:
            merged_details["retry_after_seconds"] = retry_after_seconds
        super().__init__(
            message=message,
            error_code="AI_006",
            status_code=503,
            details=merged_details,
        )