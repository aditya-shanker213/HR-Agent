"""
Embedding service.

Single source of truth for:
  - which embedding model is used
  - how documents are chunked

Used by ingest_knowledge_base.py (chunking + batch embedding)
and indirectly by vector_store.py (which uses the embedding model).
"""

from pathlib import Path

from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings

from app.core.config import settings


# --- Module-level singleton --------------------------------------------------
_embeddings = OllamaEmbeddings(
    model=settings.EMBEDDING_MODEL,
    base_url=settings.OLLAMA_BASE_URL, 
)


def get_embedding_model() -> OllamaEmbeddings:
    """Expose the embedding model for components that need it directly
    (e.g. Chroma's embedding_function). Avoids re-instantiating."""
    return _embeddings


def embed(text: str) -> list[float]:
    """Embed a single piece of text (used by query path)."""
    return _embeddings.embed_query(text)


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed many texts at once (used during ingestion)."""
    return _embeddings.embed_documents(texts)


def chunk_document(pdf_path: str) -> list:
    """Load a PDF and split it into chunks with cleaned, Chroma-safe metadata.

    Returns a list of LangChain Document objects.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    loader = PyMuPDFLoader(str(path))
    docs = loader.load()

    for d in docs:
        d.metadata["source"] = path.stem
        d.metadata["filename"] = path.name
        d.metadata["document_type"] = "hr_policy"

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(docs)

    # Clean metadata — keep only Chroma-compatible primitives
    for c in chunks:
        clean = {
            "source": str(c.metadata.get("source", "")),
            "filename": str(c.metadata.get("filename", "")),
            "document_type": str(c.metadata.get("document_type", "")),
        }
        if "page" in c.metadata:
            try:
                clean["page"] = int(c.metadata["page"])
            except (ValueError, TypeError):
                pass
        c.metadata = clean

    print(f"{path.name}: {len(docs)} pages -> {len(chunks)} chunks")
    return chunks