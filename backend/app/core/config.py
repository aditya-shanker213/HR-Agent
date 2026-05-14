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

    # Ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:3b"
    LLM_TIMEOUT_SECONDS: int = 30
    LLM_MAX_TOKENS: int = 512
    LLM_TEMPERATURE: float = 0.3

    # STT
    WHISPER_MODEL_SIZE: str = "base"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"

    # TTS
    TTS_VOICE: str = "af_heart"

    # Audio
    MAX_AUDIO_SIZE_BYTES: int = 10 * 1024 * 1024
    PROMPTS_DIR: str = "app/prompts"

    
    class Config:
        env_file = Path(__file__).parent.parent.parent / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()

get_settings.cache_clear()
settings = get_settings()