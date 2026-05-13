from typing import Any

from .base import BaseAppException


class RAGException(BaseAppException):
    def __init__(
        self,
        message: str,
        error_code: str = "RAG_BASE",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            details=details,
        )


class PolicyNotFoundException(RAGException):
    def __init__(
        self,
        message: str = "No relevant policy document found for your query.",
        query_summary: str | None = None,
        threshold: float | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if query_summary:
            merged_details["query_summary"] = query_summary
        if threshold is not None:
            merged_details["similarity_threshold"] = threshold
        super().__init__(
            message=message,
            error_code="RAG_001",
            status_code=404,
            details=merged_details,
        )


class VectorDBException(RAGException):
    def __init__(
        self,
        message: str = "The knowledge base service is temporarily unavailable.",
        operation: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if operation:
            merged_details["operation"] = operation
        super().__init__(
            message=message,
            error_code="RAG_002",
            status_code=503,
            details=merged_details,
        )


class EmbeddingGenerationException(RAGException):
    def __init__(
        self,
        message: str = "Failed to generate embeddings for the document or query.",
        document_name: str | None = None,
        query_length: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        merged_details = details or {}
        if document_name:
            merged_details["document_name"] = document_name
        if query_length is not None:
            merged_details["query_length"] = query_length
        super().__init__(
            message=message,
            error_code="RAG_003",
            status_code=500,
            details=merged_details,
        )