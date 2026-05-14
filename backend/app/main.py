from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis

from app.core.config import settings
from app.routes import health, voice


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[startup] {settings.APP_NAME} — {settings.APP_ENV}")

    # 1. Redis
    app.state.redis = await aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    try:
        await app.state.redis.ping()
        print("[startup] Redis connected")
    except Exception:
        print("[startup] WARNING: Redis not reachable — sessions will not persist")

    # 2. STT
    from app.services.stt_service import STTService
    app.state.stt = STTService()
    await app.state.stt.load_model()
    print(f"[startup] Whisper '{settings.WHISPER_MODEL_SIZE}' loaded")

    # 3. TTS
    from app.services.tts_service import TTSService
    app.state.tts = TTSService()
    await app.state.tts.load_model()
    print("[startup] Kokoro TTS loaded")

    # 4. AI
    from app.services.ai_service import AIService
    app.state.ai = AIService()
    ok = await app.state.ai.health_check()
    print(f"[startup] Ollama {'connected' if ok else 'WARNING: not reachable'}")

    yield

    # Shutdown
    await app.state.redis.aclose()
    print("[shutdown] Redis closed")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "null",  # allows file:// opened HTML
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(voice.router, prefix=settings.API_PREFIX)