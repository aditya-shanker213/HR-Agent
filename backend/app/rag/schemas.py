from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TextDocument:
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    content: str
    metadata: dict[str, Any]
    rank: int
    score: float
    semantic_score: float
    lexical_boost: float
    distance: float

    @property
    def source_name(self) -> str:
        return str(self.metadata.get("source_file", self.metadata.get("source", "unknown")))

    @property
    def page(self) -> str | int:
        return self.metadata.get("page", "unknown")

    def source_summary(self, preview_chars: int = 180) -> dict[str, Any]:
        return {
            "source": self.source_name,
            "page": self.page,
            "rank": self.rank,
            "score": round(self.score, 4),
            "semantic_score": round(self.semantic_score, 4),
            "lexical_boost": round(self.lexical_boost, 4),
            "preview": self.content[:preview_chars].replace("\n", " ") + "...",
        }


@dataclass(frozen=True)
class RAGResponse:
    answer: str
    sources: list[dict[str, Any]]
    latency_seconds: float
    retrieval_seconds: float
    generation_seconds: float
    done_reason: str | None = None


@dataclass(frozen=True)
class RAGStreamEvent:
    event: str
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
