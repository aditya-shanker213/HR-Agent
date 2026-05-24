from __future__ import annotations

import re
import time

import numpy as np

from .embeddings import EmbeddingManager
from .schemas import TextDocument


class SemanticChunker:
    """Group adjacent sentences when embeddings remain semantically close."""

    def __init__(
        self,
        embedding_manager: EmbeddingManager,
        min_chunk_chars: int = 350,
        max_chunk_chars: int = 1000,
        breakpoint_percentile: int = 85,
    ):
        self.embedding_manager = embedding_manager
        self.min_chunk_chars = min_chunk_chars
        self.max_chunk_chars = max_chunk_chars
        self.breakpoint_percentile = breakpoint_percentile

    @staticmethod
    def _split_units(text: str) -> list[str]:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return []
        units = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", cleaned)
        units = [unit.strip() for unit in units if len(unit.strip()) >= 20]
        return units or [cleaned]

    def split_documents(self, docs: list[TextDocument]) -> list[TextDocument]:
        started = time.perf_counter()
        chunks: list[TextDocument] = []

        for doc in docs:
            units = self._split_units(doc.content)
            if not units:
                continue

            if len(units) == 1:
                break_distances = np.array([], dtype=np.float32)
                threshold = 1.0
            else:
                unit_embeddings = self.embedding_manager.embed_documents(units, show_progress_bar=False)
                adjacent_similarity = np.sum(unit_embeddings[:-1] * unit_embeddings[1:], axis=1)
                break_distances = 1 - adjacent_similarity
                threshold = float(np.percentile(break_distances, self.breakpoint_percentile))

            current_units: list[str] = []
            current_chars = 0
            chunk_index = 0

            def flush_chunk() -> None:
                nonlocal chunk_index, current_units, current_chars
                if not current_units:
                    return
                chunk_text = " ".join(current_units).strip()
                metadata = dict(doc.metadata)
                metadata["chunk_index"] = chunk_index
                metadata["chunk_chars"] = len(chunk_text)
                metadata["chunker"] = "semantic_adjacent_similarity"
                chunks.append(TextDocument(content=chunk_text, metadata=metadata))
                chunk_index += 1
                current_units = []
                current_chars = 0

            for idx, unit in enumerate(units):
                should_break = (
                    idx > 0
                    and bool(current_units)
                    and current_chars >= self.min_chunk_chars
                    and break_distances[idx - 1] >= threshold
                )
                would_overflow = current_chars + len(unit) + 1 > self.max_chunk_chars
                if should_break or would_overflow:
                    flush_chunk()
                current_units.append(unit)
                current_chars += len(unit) + 1
            flush_chunk()

        print(f"Created {len(chunks)} semantic chunk(s) in {time.perf_counter() - started:.2f}s")
        return chunks

