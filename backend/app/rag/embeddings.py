from __future__ import annotations

import time

import numpy as np
from sentence_transformers import SentenceTransformer


class EmbeddingManager:
    """SentenceTransformer wrapper using BGE query/passage prefixes."""

    def __init__(self, model_name: str, batch_size: int = 32):
        self.model_name = model_name
        self.batch_size = batch_size
        started = time.perf_counter()
        self.model = SentenceTransformer(model_name)
        if hasattr(self.model, "get_embedding_dimension"):
            self.dimension = self.model.get_embedding_dimension()
        else:
            self.dimension = self.model.get_sentence_embedding_dimension()
        print(f"Loaded embedding model {model_name} ({self.dimension} dims) in {time.perf_counter() - started:.2f}s")

    def _encode(self, texts: list[str], prefix: str, show_progress_bar: bool = False) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        prepared = [f"{prefix}{text}" for text in texts]
        embeddings = self.model.encode(
            prepared,
            batch_size=self.batch_size,
            show_progress_bar=show_progress_bar,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return embeddings.astype(np.float32)

    def embed_documents(self, texts: list[str], show_progress_bar: bool = True) -> np.ndarray:
        return self._encode(texts, "passage: ", show_progress_bar)

    def embed_query(self, query: str) -> np.ndarray:
        return self._encode([query], "query: ", False)[0]
