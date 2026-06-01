# backend/app/services/vector_store.py

from pinecone import Pinecone, ServerlessSpec
from app.core.config import settings


class VectorStore:
    """
    Talks to Pinecone.
    Handles upsert (save vectors) and query (search vectors).
    """

    def __init__(self):
        self._index = None
        self._pc = None

    def connect(self) -> None:
        """Connect to Pinecone and get index reference."""
        self._pc = Pinecone(api_key=settings.PINECONE_API_KEY)

        # Check if index exists
        existing = [i.name for i in self._pc.list_indexes()]

        if settings.PINECONE_INDEX_NAME not in existing:
            # Create if it doesn't exist
            self._pc.create_index(
                name=settings.PINECONE_INDEX_NAME,
                dimension=settings.EMBEDDING_DIMENSION,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud=settings.PINECONE_CLOUD,
                    region=settings.PINECONE_REGION,
                )
            )
            print(f"[vector_store] Created index: {settings.PINECONE_INDEX_NAME}")

        self._index = self._pc.Index(settings.PINECONE_INDEX_NAME)
        print(f"[startup] Pinecone connected → index: {settings.PINECONE_INDEX_NAME}")

    async def upsert(self, vectors: list[dict]) -> None:
        """
        Save vectors to Pinecone.
        vectors format:
        [{"id": "chunk_001", "values": [...], "metadata": {"text": "...", "section": "..."}}]
        """
        if not self._index:
            raise RuntimeError("Vector store not connected.")

        # Pinecone upsert in batches of 100
        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            self._index.upsert(vectors=batch)

        print(f"[vector_store] Upserted {len(vectors)} vectors")

    async def search(
        self,
        query_vector: list[float],
        top_k: int = None,
        filter: dict = None,
    ) -> list[dict]:
        """
        Search for similar vectors.
        Returns list of matches with text and metadata.
        """
        if not self._index:
            raise RuntimeError("Vector store not connected.")

        k = top_k or settings.RAG_TOP_K

        results = self._index.query(
            vector=query_vector,
            top_k=k,
            include_metadata=True,
            filter=filter,
        )

        matches = []
        for match in results.matches:
            matches.append({
                "id":       match.id,
                "score":    match.score,
                "text":     match.metadata.get("text", ""),
                "section":  match.metadata.get("section", ""),
                "doc_id":   match.metadata.get("doc_id", ""),
            })

        return matches

    def get_stats(self) -> dict:
        """Returns index statistics — useful for health check."""
        if not self._index:
            return {"status": "not connected"}
        stats = self._index.describe_index_stats()
        return {"total_vectors": stats.total_vector_count}