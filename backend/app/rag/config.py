from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def find_project_root(start: Path | None = None) -> Path:
    """Find the repository root without relying on notebook working directory state."""
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists() and (candidate / "backend").exists():
            return candidate
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class RAGConfig:
    project_root: Path
    pdf_dir: Path
    vector_store_dir: Path
    chroma_collection: str
    embedding_model: str
    llm_provider: str
    ollama_base_url: str
    ollama_model: str
    top_k: int = 4
    fetch_k: int = 32
    mmr_lambda: float = 0.65
    max_context_chars_per_chunk: int = 700
    max_generation_seconds: int = 35
    generation_temperature: float = 0.0
    generation_top_p: float = 0.7
    generation_top_k: int = 20
    generation_num_ctx: int = 1536
    generation_num_predict: int = 180
    embedding_batch_size: int = 32

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "RAGConfig":
        root = find_project_root(project_root)
        load_dotenv(root / ".env")
        load_dotenv(root / "notebook" / ".env")

        pdf_dir = Path(os.getenv("RAG_PDF_DIR", root / "notebook" / "pdf_dir"))
        vector_store_dir = Path(os.getenv("RAG_VECTOR_STORE_DIR", root / "data" / "vector_store_bge_chroma"))

        return cls(
            project_root=root,
            pdf_dir=pdf_dir,
            vector_store_dir=vector_store_dir,
            chroma_collection=os.getenv("CHROMA_COLLECTION", "hr_documents_bge_small_semantic_chunks"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
            llm_provider=os.getenv("LLM_PROVIDER", "ollama"),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
            top_k=int(os.getenv("RAG_TOP_K", "4")),
            fetch_k=int(os.getenv("RAG_FETCH_K", "32")),
            mmr_lambda=float(os.getenv("RAG_MMR_LAMBDA", "0.65")),
            max_context_chars_per_chunk=int(os.getenv("RAG_MAX_CONTEXT_CHARS_PER_CHUNK", "700")),
            max_generation_seconds=int(os.getenv("RAG_MAX_GENERATION_SECONDS", "35")),
            generation_temperature=float(os.getenv("RAG_GENERATION_TEMPERATURE", "0.0")),
            generation_top_p=float(os.getenv("RAG_GENERATION_TOP_P", "0.7")),
            generation_top_k=int(os.getenv("RAG_GENERATION_TOP_K", "20")),
            generation_num_ctx=int(os.getenv("RAG_GENERATION_NUM_CTX", "1536")),
            generation_num_predict=int(os.getenv("RAG_GENERATION_NUM_PREDICT", "180")),
            embedding_batch_size=int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", "32")),
        )

    @property
    def ollama_options(self) -> dict[str, int | float]:
        return {
            "temperature": self.generation_temperature,
            "top_p": self.generation_top_p,
            "top_k": self.generation_top_k,
            "num_ctx": self.generation_num_ctx,
            "num_predict": self.generation_num_predict,
        }
