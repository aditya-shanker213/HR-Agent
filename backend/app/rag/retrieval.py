from __future__ import annotations

import re
import time

import numpy as np

from .embeddings import EmbeddingManager
from .schemas import RetrievedChunk
from .vector_store import ChromaVectorStore


def lexical_rerank_score(query: str, document: str) -> float:
    """Cheap document-agnostic reranker while a cross-encoder is optional."""
    q = query.lower()
    d = document.lower()
    query_terms = {term for term in re.findall(r"[a-z][a-z0-9_-]+", q) if len(term) > 2}
    doc_terms = {term for term in re.findall(r"[a-z][a-z0-9_-]+", d) if len(term) > 2}
    score = 0.015 * len(query_terms & doc_terms)

    if any(marker in d for marker in ["list of tables", "table no.", "page no.", "list of figures", "table of contents"]):
        score -= 0.45

    marker_groups = {
        ("policy", "policies", "rule", "rules", "guideline", "guidelines"): [
            "policy",
            "guideline",
            "eligibility",
            "approval",
            "exception",
            "compliance",
            "procedure",
            "process",
        ],
        ("leave", "vacation", "holiday", "pto", "absence", "attendance"): [
            "leave",
            "vacation",
            "holiday",
            "pto",
            "absence",
            "attendance",
            "working days",
            "approval",
        ],
        ("payroll", "salary", "compensation", "bonus", "reimbursement", "tax", "benefit", "benefits"): [
            "payroll",
            "salary",
            "compensation",
            "bonus",
            "reimbursement",
            "tax",
            "benefit",
            "benefits",
        ],
        ("onboarding", "joining", "probation", "exit", "resignation", "termination"): [
            "onboarding",
            "joining",
            "probation",
            "exit",
            "resignation",
            "termination",
            "notice period",
        ],
        ("training", "learning", "development", "certification"): [
            "training",
            "learning",
            "development",
            "certification",
            "course",
            "program",
        ],
    }
    for triggers, markers in marker_groups.items():
        if any(trigger in q for trigger in triggers):
            score += 0.08 * sum(marker in d for marker in markers)
    return score


def maximal_marginal_relevance(
    candidate_embeddings: np.ndarray,
    candidate_scores: np.ndarray,
    top_k: int,
    lambda_mult: float,
) -> list[int]:
    if len(candidate_embeddings) == 0:
        return []
    selected: list[int] = []
    remaining = list(range(len(candidate_embeddings)))

    while remaining and len(selected) < top_k:
        if not selected:
            best_idx = max(remaining, key=lambda idx: candidate_scores[idx])
        else:
            selected_embeddings = candidate_embeddings[selected]
            mmr_scores = {}
            for idx in remaining:
                redundancy = float(np.max(selected_embeddings @ candidate_embeddings[idx]))
                mmr_scores[idx] = lambda_mult * float(candidate_scores[idx]) - (1 - lambda_mult) * redundancy
            best_idx = max(remaining, key=lambda idx: mmr_scores[idx])
        selected.append(best_idx)
        remaining.remove(best_idx)
    return selected


class RAGRetriever:
    def __init__(self, vector_store: ChromaVectorStore, embedding_manager: EmbeddingManager):
        self.vector_store = vector_store
        self.embedding_manager = embedding_manager

    def retrieve(self, query: str, top_k: int, fetch_k: int, lambda_mult: float, min_score: float = 0.0) -> tuple[list[RetrievedChunk], float]:
        started = time.perf_counter()
        query_embedding = self.embedding_manager.embed_query(query)
        total = self.vector_store.collection.count()
        n_results = min(max(fetch_k, top_k * 8), total)
        if n_results == 0:
            return [], time.perf_counter() - started

        results = self.vector_store.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=n_results,
            include=["documents", "metadatas", "distances", "embeddings"],
        )
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        ids = results.get("ids", [[]])[0]
        embeddings = np.array(results.get("embeddings", [[]])[0], dtype=np.float32)

        semantic_scores = embeddings @ query_embedding
        lexical_scores = np.array([lexical_rerank_score(query, doc) for doc in documents], dtype=np.float32)
        candidate_scores = semantic_scores + lexical_scores
        selected = maximal_marginal_relevance(embeddings, candidate_scores, top_k, lambda_mult)

        chunks: list[RetrievedChunk] = []
        for rank, idx in enumerate(selected, start=1):
            score = float(candidate_scores[idx])
            if score < min_score:
                continue
            chunks.append(
                RetrievedChunk(
                    id=ids[idx],
                    content=documents[idx],
                    metadata=metadatas[idx] or {},
                    rank=rank,
                    score=score,
                    semantic_score=float(semantic_scores[idx]),
                    lexical_boost=float(lexical_scores[idx]),
                    distance=float(distances[idx]),
                )
            )
        return chunks, time.perf_counter() - started
