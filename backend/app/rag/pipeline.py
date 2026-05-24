from __future__ import annotations

import re
import time
from collections.abc import Iterator

from .answering import build_messages, extractive_fallback_answer
from .chunking import SemanticChunker
from .config import RAGConfig
from .documents import PDFDocumentLoader
from .embeddings import EmbeddingManager
from .llm_clients import LLMBackendError, LLMClient, build_llm_client
from .retrieval import RAGRetriever
from .schemas import RAGResponse, RAGStreamEvent, RetrievedChunk
from .vector_store import ChromaVectorStore


class RAGPipeline:
    def __init__(self, config: RAGConfig, llm_client: LLMClient | None = None):
        self.config = config
        self.embedding_manager = EmbeddingManager(config.embedding_model, batch_size=config.embedding_batch_size)
        self.vector_store = ChromaVectorStore(config.chroma_collection, config.vector_store_dir, self.embedding_manager)
        self.retriever = RAGRetriever(self.vector_store, self.embedding_manager)
        self.llm_client = llm_client or build_llm_client(config)

    def index_pdfs(self, rebuild: bool = False) -> dict[str, int]:
        pages = PDFDocumentLoader(self.config.pdf_dir).load()
        chunks = SemanticChunker(self.embedding_manager).split_documents(pages)
        return self.vector_store.upsert_documents(chunks, rebuild=rebuild)

    def retrieve(self, query: str) -> tuple[list[RetrievedChunk], float]:
        return self.retriever.retrieve(
            query=query,
            top_k=self.config.top_k,
            fetch_k=self.config.fetch_k,
            lambda_mult=self.config.mmr_lambda,
        )

    @staticmethod
    def _looks_like_context_copy(answer: str, chunks: list[RetrievedChunk]) -> bool:
        cleaned_answer = re.sub(r"\s+", " ", answer).strip().lower()
        if not cleaned_answer:
            return False
        if any(marker in cleaned_answer for marker in ["context:", "[source", "source 1", "source 2"]):
            return True
        combined_context = re.sub(r"\s+", " ", " ".join(chunk.content for chunk in chunks)).lower()
        if len(cleaned_answer) > 180 and cleaned_answer in combined_context:
            return True
        if len(cleaned_answer) > 120 and cleaned_answer[:120] in combined_context:
            return True
        answer_sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", cleaned_answer) if len(sentence.strip()) > 60]
        if answer_sentences:
            copied_sentences = sum(1 for sentence in answer_sentences if sentence in combined_context)
            if copied_sentences / len(answer_sentences) > 0.5:
                return True
        answer_words = cleaned_answer.split()
        if len(answer_words) < 35:
            return False
        answer_windows = {" ".join(answer_words[i : i + 10]) for i in range(0, max(len(answer_words) - 9, 0))}
        if not answer_windows:
            return False
        copied_windows = sum(1 for window in answer_windows if window in combined_context)
        return copied_windows / len(answer_windows) > 0.35

    def answer(self, query: str) -> RAGResponse:
        started = time.perf_counter()
        chunks, retrieval_seconds = self.retrieve(query)
        sources = [chunk.source_summary() for chunk in chunks]
        if not chunks:
            return RAGResponse(
                answer="No relevant context found.",
                sources=[],
                latency_seconds=round(time.perf_counter() - started, 2),
                retrieval_seconds=round(retrieval_seconds, 2),
                generation_seconds=0.0,
            )

        messages = build_messages(query, chunks, self.config.max_context_chars_per_chunk)
        try:
            answer, done_reason, generation_seconds = self.llm_client.generate(messages)
        except LLMBackendError as exc:
            answer = extractive_fallback_answer(query, chunks)
            return RAGResponse(
                answer=answer,
                sources=sources,
                latency_seconds=round(time.perf_counter() - started, 2),
                retrieval_seconds=round(retrieval_seconds, 2),
                generation_seconds=0.0,
                done_reason=exc.reason,
            )
        if self._looks_like_context_copy(answer, chunks):
            retry_messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "Your previous draft copied the document text. Rewrite it as a synthesized HR assistant "
                        "answer in your own words, using only the same context. Do not quote or paste the context."
                    ),
                },
            ]
            try:
                answer, retry_reason, retry_seconds = self.llm_client.generate(retry_messages)
            except LLMBackendError as exc:
                answer = extractive_fallback_answer(query, chunks)
                done_reason = exc.reason
                generation_seconds = 0.0
            else:
                done_reason = f"retry_after_context_copy:{retry_reason}"
                generation_seconds += retry_seconds
        if not answer:
            answer = extractive_fallback_answer(query, chunks)
            done_reason = done_reason or "fallback_answer"

        return RAGResponse(
            answer=answer,
            sources=sources,
            latency_seconds=round(time.perf_counter() - started, 2),
            retrieval_seconds=round(retrieval_seconds, 2),
            generation_seconds=round(generation_seconds, 2),
            done_reason=done_reason,
        )

    def answer_stream(self, query: str) -> Iterator[str]:
        for event in self.answer_stream_events(query):
            if event.event == "chunk":
                yield event.text

    def answer_stream_events(self, query: str) -> Iterator[RAGStreamEvent]:
        started = time.perf_counter()
        chunks, retrieval_seconds = self.retrieve(query)
        sources = [chunk.source_summary() for chunk in chunks]
        if not chunks:
            latency_seconds = round(time.perf_counter() - started, 2)
            yield RAGStreamEvent(event="chunk", text="No relevant context found.")
            yield RAGStreamEvent(
                event="metadata",
                metadata={
                    "latency_seconds": latency_seconds,
                    "retrieval_seconds": round(retrieval_seconds, 2),
                    "generation_seconds": 0.0,
                    "done_reason": "no_relevant_context",
                    "sources": sources,
                },
            )
            return

        messages = build_messages(query, chunks, self.config.max_context_chars_per_chunk)
        generation_started = time.perf_counter()
        done_reason = "stream_complete"
        try:
            for part in self.llm_client.stream(messages):
                yield RAGStreamEvent(event="chunk", text=part)
        except LLMBackendError as exc:
            done_reason = exc.reason
            yield RAGStreamEvent(event="chunk", text=extractive_fallback_answer(query, chunks))
        finally:
            latency_seconds = time.perf_counter() - started
            generation_seconds = time.perf_counter() - generation_started
            yield RAGStreamEvent(
                event="metadata",
                metadata={
                    "latency_seconds": round(latency_seconds, 2),
                    "retrieval_seconds": round(retrieval_seconds, 2),
                    "generation_seconds": round(generation_seconds, 2),
                    "done_reason": done_reason,
                    "sources": sources,
                },
            )
