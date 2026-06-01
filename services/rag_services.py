"""
RAG service.

Orchestrates knowledge-base question answering:
  1. retrieve candidates from vector_store
  2. rerank with cross-encoder for true relevance
  3. format top chunks and ask the LLM
  4. return structured answer with sources

Called by rag_node in the LangGraph graph.
"""

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from flashrank import Ranker, RerankRequest

from app.core.config import settings
from app.services import vector_store


# --- Module-level singletons -------------------------------------------------
_llm = ChatOllama(
    model=settings.LLM_MODEL,
    base_url=settings.OLLAMA_BASE_URL,
    temperature=settings.LLM_TEMPERATURE,
    num_ctx=settings.LLM_NUM_CTX,
)

_reranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")

SYSTEM_PROMPT = """You are an HR assistant answering questions from a company knowledge base.
Use ONLY the provided context to answer. If the answer is not in the context, say:
"I don't have that information in the knowledge base."
Be concise. When you use a fact, mention the source and page in parentheses."""

USER_PROMPT = """Context:
{context}

Question: {question}

Answer:"""

_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("user", USER_PROMPT),
])

_answer_chain = _prompt | _llm | StrOutputParser()


# --- Internal helpers --------------------------------------------------------
def _format_docs(docs: list) -> str:
    parts = []
    for i, d in enumerate(docs, 1):
        src = d.metadata.get("source", "unknown")
        page = d.metadata.get("page", "?")
        parts.append(f"[{i}] (source: {src}, page: {page})\n{d.page_content}")
    return "\n\n".join(parts)


def _rerank(query: str, candidates: list) -> list:
    if not candidates:
        return []
    passages = [
        {"id": i, "text": d.page_content, "meta": d.metadata}
        for i, d in enumerate(candidates)
    ]
    ranked = _reranker.rerank(RerankRequest(query=query, passages=passages))
    top_ids = [r["id"] for r in ranked[: settings.RERANK_TOP_N]]
    return [candidates[i] for i in top_ids]


# --- Public interface --------------------------------------------------------
def embed_and_search(
    query: str,
    top_k: int = None,
    metadata_filter: dict | None = None,
) -> list:
    """Retrieve and rerank chunks. Returns top-N Documents."""
    candidates = vector_store.similarity_search(
        query, top_k=top_k, metadata_filter=metadata_filter
    )
    return _rerank(query, candidates)


def answer(query: str, metadata_filter: dict | None = None) -> dict:
    """Full RAG flow. Returns {answer, sources, chunks_used}."""
    if not query or not query.strip():
        raise ValueError("Query cannot be empty.")

    chunks = embed_and_search(query, metadata_filter=metadata_filter)

    if not chunks:
        return {
            "answer": "I don't have that information in the knowledge base.",
            "sources": [],
            "chunks_used": 0,
        }

    context = _format_docs(chunks)
    response = _answer_chain.invoke({"context": context, "question": query})

    sources = [
        {
            "source": d.metadata.get("source"),
            "page": d.metadata.get("page"),
            "snippet": d.page_content[:200].replace("\n", " "),
        }
        for d in chunks
    ]

    return {
        "answer": response,
        "sources": sources,
        "chunks_used": len(chunks),
    }