from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Literal
from pathlib import Path

class Settings(BaseSettings):
    # App
    APP_NAME: str = "HR Voice Agent"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    SESSION_TTL_SECONDS: int = 3600

    # MongoDB# MongoDB
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "hr_agent"

    # Ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:3b"
    LLM_TIMEOUT_SECONDS: int = 30
    LLM_MAX_TOKENS: int = 512
    LLM_TEMPERATURE: float = 0.3

    # STT
    WHISPER_MODEL_SIZE: str = "small"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"

    # TTS
    TTS_VOICE: str = "af_heart"

    # Audio
    MAX_AUDIO_SIZE_BYTES: int = 10 * 1024 * 1024
    PROMPTS_DIR: str = "app/prompts"

    # Pinecone
    PINECONE_API_KEY: str = "pcsk_iP9m7_CrXy3feCJzdiTCVCbkdeYf2ip8PgoJmHLWP7uw94iqium1xBY2SsQUgNFG1AM5y"
    PINECONE_INDEX_NAME: str = "hr-policies"
    PINECONE_CLOUD: str = "aws"
    PINECONE_REGION: str = "us-east-1"

    # Embedding
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384
    RAG_TOP_K: int = 3

    
    class Config:
        env_file = Path(__file__).parent.parent.parent / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()

get_settings.cache_clear()
settings = get_settings()