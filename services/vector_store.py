"""
Vector store service.

DB-agnostic abstraction over the vector database. Today it's Chroma;
swapping to Qdrant later means changing only this file.
"""

from pathlib import Path

from langchain_chroma import Chroma

from app.core.config import settings
from app.services.embedding_service import get_embedding_model


# --- Module-level singleton --------------------------------------------------
Path(settings.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)

_store = Chroma(
    collection_name=settings.CHROMA_COLLECTION,
    embedding_function=get_embedding_model(),
    persist_directory=settings.CHROMA_PERSIST_DIR,
)


def similarity_search(
    query: str,
    top_k: int = None,
    metadata_filter: dict | None = None,
) -> list:
    """Search the vector store. Returns LangChain Document objects."""
    k = top_k or settings.RETRIEVER_K

    if settings.RETRIEVER_TYPE == "mmr":
        return _store.max_marginal_relevance_search(
            query,
            k=k,
            fetch_k=settings.MMR_FETCH_K,
            lambda_mult=settings.MMR_LAMBDA_MULT,
            filter=metadata_filter,
        )
    return _store.similarity_search(query, k=k, filter=metadata_filter)


def add_documents(chunks: list) -> None:
    """Add chunked Documents to the store."""
    _store.add_documents(chunks)


def delete_by_source(source_name: str) -> None:
    """Remove all chunks belonging to a given source document.
    Used when re-ingesting an updated document."""
    _store.delete(where={"source": source_name})


def list_sources() -> list[str]:
    """Return the distinct source document names currently in the store."""
    data = _store.get(include=["metadatas"])
    sources = {
        m.get("source")
        for m in data.get("metadatas", [])
        if m and m.get("source")
    }
    return sorted(sources)