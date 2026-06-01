# backend/app/services/rag_service.py

import re
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore
from app.core.config import settings


class RAGService:
    def __init__(self, embedding_service: EmbeddingService, vector_store: VectorStore):
        self.embedder     = embedding_service
        self.vector_store = vector_store

    def _expand_query(self, query: str) -> str:
        """
        Fix common speech-to-text mistakes for HR terms.
        Whisper often mishears domain-specific words.
        """
        corrections = {
            r'\bleaf\b':      'leave',
            r'\bleafs\b':     'leaves',
            r'\bpayrow\b':    'payroll',
            r'\bpayrol\b':    'payroll',
            r'\baprisal\b':   'appraisal',
            r'\bapraised\b':  'appraised',
            r'\bgrievious\b': 'grievance',
            r'\bposh\b':      'sexual harassment',
            r'\bprobashion\b':'probation',
        }
        result = query
        for pattern, replacement in corrections.items():
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        if result != query:
            print(f"[rag_service] query corrected: '{query}' → '{result}'")

        return result

    async def retrieve(self, query: str, top_k: int = None) -> list[dict]:
        """
        Given a question, find the most relevant policy chunks.
        Returns list of {"text": "...", "section": "...", "score": ...}
        """
        # Fix speech-to-text mistakes
        cleaned_query = self._expand_query(query)

        # Embed the cleaned query
        query_vector = await self.embedder.embed(cleaned_query)

        # Search Pinecone
        matches = await self.vector_store.search(
            query_vector=query_vector,
            top_k=top_k or settings.RAG_TOP_K,
        )

        # Filter low-confidence matches
        relevant = [m for m in matches if m["score"] > 0.3]

        print(f"[rag_service] query: '{cleaned_query}' → {len(relevant)} relevant chunks found")
        for m in relevant:
            print(f"  score: {m['score']:.3f} | section: {m['section']}")

        return relevant                