"""Production RAG package for document-grounded HR assistant retrieval."""

from .config import RAGConfig

__all__ = ["RAGConfig", "RAGPipeline", "RAGService"]


def __getattr__(name: str):
    if name == "RAGPipeline":
        from .pipeline import RAGPipeline

        return RAGPipeline
    if name == "RAGService":
        from .service import RAGService

        return RAGService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
