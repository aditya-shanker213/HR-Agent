import os

class Settings:
    # Ollama
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2:3b")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

    # Vector store
    CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma_db")
    CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "hr_policy")

    # Retrieval / chunking
    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 150
    RETRIEVER_K = 8
    RETRIEVER_TYPE = "mmr"          # "similarity" or "mmr"
    MMR_FETCH_K = 20                # candidates to pull before MMR selects final k
    MMR_LAMBDA_MULT = 0.5           # 1 = max relevance, 0 = max diversity
    RERANK_TOP_N = 4

    # LLM
    LLM_TEMPERATURE = 0
    LLM_NUM_CTX = 4096


settings = Settings()