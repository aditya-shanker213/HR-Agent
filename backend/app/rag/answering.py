from __future__ import annotations

import re

from .schemas import RetrievedChunk


def format_context(chunks: list[RetrievedChunk], max_chars_per_chunk: int) -> str:
    blocks = []
    for idx, chunk in enumerate(chunks, start=1):
        text = re.sub(r"\s+", " ", chunk.content).strip()
        if len(text) > max_chars_per_chunk:
            text = text[:max_chars_per_chunk].rsplit(" ", 1)[0] + "..."
        blocks.append(f"[Source {idx}] {text}")
    return "\n\n".join(blocks)


def build_messages(query: str, chunks: list[RetrievedChunk], max_chars_per_chunk: int) -> list[dict[str, str]]:
    context = format_context(chunks, max_chars_per_chunk)
    system = (
        "You are an HR AI assistant answering from uploaded documents. Use only the provided context. "
        "Synthesize a new answer in your own words instead of copying the context. "
        "Do not quote long passages. Never explain your reasoning. Never mention the user or the prompt. "
        "If the answer is not explicitly in the context, say: I could not find that in the uploaded documents. "
        "Keep the answer concise and practical."
    )
    user = f"""Context:
{context}

Question: {query}

Write a fresh, direct answer based on the context. Do not paste the context back."""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def extractive_fallback_answer(query: str, chunks: list[RetrievedChunk], max_sentences: int = 2) -> str:
    query_terms = {term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9_-]+", query) if len(term) > 2}
    boost_terms = {
        "policy",
        "leave",
        "salary",
        "payroll",
        "benefit",
        "benefits",
        "training",
        "approval",
        "eligibility",
        "employee",
        "manager",
        "hr",
        "process",
        "procedure",
        "timeline",
        "days",
        "documents",
    }
    candidates = []
    for chunk in chunks:
        text = re.sub(r"\s+", " ", chunk.content).strip()
        if any(marker in text.lower() for marker in ["list of tables", "table no.", "page no.", "list of figures"]):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            sentence_terms = {term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9_-]+", sentence)}
            score = len(query_terms & sentence_terms) + 2 * len(boost_terms & sentence_terms)
            if score > 0 and len(sentence) > 30:
                candidates.append((score, chunk.rank, sentence.strip()))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    if not candidates:
        return "I could not find that in the uploaded documents."

    picked = []
    seen = set()
    for _, rank, sentence in candidates:
        if sentence in seen:
            continue
        picked.append(f"{sentence} [Source {rank}]")
        seen.add(sentence)
        if len(picked) >= max_sentences:
            break
    return " ".join(picked)
