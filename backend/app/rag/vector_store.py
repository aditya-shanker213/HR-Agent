from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import chromadb

from .embeddings import EmbeddingManager
from .schemas import TextDocument


def sanitize_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    clean: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        clean[key] = value if isinstance(value, (str, int, float, bool)) else str(value)
    return clean


def stable_chunk_id(doc: TextDocument) -> str:
    source = doc.metadata.get("source_file", doc.metadata.get("source", "unknown"))
    page = doc.metadata.get("page", "unknown")
    chunk_index = doc.metadata.get("chunk_index", "unknown")
    raw = f"{source}|{page}|{chunk_index}|{doc.content}"
    return f"chunk_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:24]}"


class ChromaVectorStore:
    def __init__(self, collection_name: str, persist_directory: Path, embedding_manager: EmbeddingManager):
        self.collection_name = collection_name
        self.persist_directory = Path(persist_directory)
        self.embedding_manager = embedding_manager
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.persist_directory))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={
                "description": "Document semantic chunks for production RAG",
                "embedding_model": embedding_manager.model_name,
                "embedding_dimension": embedding_manager.dimension,
            },
        )

    def rebuild_collection(self) -> None:
        try:
            self.client.delete_collection(self.collection_name)
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={
                "description": "Document semantic chunks for production RAG",
                "embedding_model": self.embedding_manager.model_name,
                "embedding_dimension": self.embedding_manager.dimension,
            },
        )

    def _existing_ids(self, ids: list[str], batch_size: int = 500) -> set[str]:
        existing: set[str] = set()
        for start in range(0, len(ids), batch_size):
            found = self.collection.get(ids=ids[start : start + batch_size])
            existing.update(found.get("ids", []))
        return existing

    def upsert_documents(self, documents: list[TextDocument], rebuild: bool = False) -> dict[str, int]:
        started = time.perf_counter()
        if rebuild:
            self.rebuild_collection()

        ids = [stable_chunk_id(doc) for doc in documents]
        existing_ids = set() if rebuild else self._existing_ids(ids)
        missing_items = [(doc_id, doc) for doc_id, doc in zip(ids, documents) if doc_id not in existing_ids]

        if not missing_items:
            return {"indexed": 0, "skipped": len(documents), "total": self.collection.count()}

        missing_ids = [item[0] for item in missing_items]
        missing_docs = [item[1] for item in missing_items]
        texts = [doc.content for doc in missing_docs]
        metadatas = [sanitize_metadata(doc.metadata) for doc in missing_docs]
        embeddings = self.embedding_manager.embed_documents(texts, show_progress_bar=True)

        self.collection.upsert(
            ids=missing_ids,
            documents=texts,
            metadatas=metadatas,
            embeddings=embeddings.tolist(),
        )
        print(f"Indexed {len(missing_docs)} chunk(s) in {time.perf_counter() - started:.2f}s")
        return {"indexed": len(missing_docs), "skipped": len(documents) - len(missing_docs), "total": self.collection.count()}
