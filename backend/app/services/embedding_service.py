# backend/app/services/embedding_service.py

import asyncio
from typing import Optional
from app.core.config import settings


class EmbeddingService:
    """
    Converts text to vectors using sentence-transformers.
    Runs locally — no API key, no cost, works on M1.
    Model: all-MiniLM-L6-v2 → 384-dimension vectors.
    """

    def __init__(self):
        self._model = None

    def is_loaded(self) -> bool:
        return self._model is not None

    async def load_model(self) -> None:
        """Load embedding model at startup."""
        loop = asyncio.get_event_loop()

        def _load():
            from sentence_transformers import SentenceTransformer
            return SentenceTransformer(settings.EMBEDDING_MODEL)

        self._model = await loop.run_in_executor(None, _load)
        print(f"[startup] Embedding model '{settings.EMBEDDING_MODEL}' loaded")

    async def embed(self, text: str) -> list[float]:
        """Convert a single text string to a vector."""
        if not self._model:
            raise RuntimeError("Embedding model not loaded.")

        loop = asyncio.get_event_loop()
        vector = await loop.run_in_executor(
            None,
            lambda: self._model.encode(text, normalize_embeddings=True).tolist()
        )
        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Convert multiple texts to vectors in one batch — faster than one by one."""
        if not self._model:
            raise RuntimeError("Embedding model not loaded.")

        loop = asyncio.get_event_loop()
        vectors = await loop.run_in_executor(
            None,
            lambda: self._model.encode(
                texts,
                normalize_embeddings=True,
                batch_size=32,
                show_progress_bar=True,
            ).tolist()
        )
        return vectors