from __future__ import annotations

from collections.abc import Iterator

from .config import RAGConfig
from .pipeline import RAGPipeline
from .schemas import RAGResponse, RAGStreamEvent


class RAGService:
    """Stable integration surface for API, STT, and TTS layers."""

    def __init__(self, config: RAGConfig | None = None):
        self.config = config or RAGConfig.from_env()
        self.pipeline = RAGPipeline(self.config)

    def index(self, rebuild: bool = False) -> dict[str, int]:
        return self.pipeline.index_pdfs(rebuild=rebuild)

    def answer(self, query: str) -> RAGResponse:
        return self.pipeline.answer(query)

    def answer_stream(self, query: str) -> Iterator[str]:
        return self.pipeline.answer_stream(query)

    def answer_stream_events(self, query: str) -> Iterator[RAGStreamEvent]:
        return self.pipeline.answer_stream_events(query)
