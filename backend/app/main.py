# backend/app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis

from app.core.config import settings
from app.routes import health, voice
from app.routes.auth_routes import router as auth_router
from app.routes.super_admin_routes import router as super_admin_router
from app.routes.admin_routes import router as admin_router
from app.routes.hr_routes import router as hr_router
from app.database.mongo_connection import connect_mongo, disconnect_mongo


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis
    app.state.redis = await aioredis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )
    try:
        await app.state.redis.ping()
        print("[startup] Redis connected")
    except Exception:
        print("[startup] WARNING: Redis not reachable")

    # MongoDB (async — for agent tools)
    await connect_mongo()

    # STT
    from app.services.stt_service import STTService
    app.state.stt = STTService()
    await app.state.stt.load_model()
    print(f"[startup] Whisper '{settings.WHISPER_MODEL_SIZE}' loaded")

    # TTS
    from app.services.tts_service import TTSService
    app.state.tts = TTSService()
    await app.state.tts.load_model()
    print("[startup] Kokoro TTS loaded")

    # AI
    from app.services.ai_service import AIService
    app.state.ai = AIService()
    ok = await app.state.ai.health_check()
    print(f"[startup] Ollama {'connected' if ok else 'WARNING: not reachable'}")

    # Embedding
    from app.services.embedding_service import EmbeddingService
    app.state.embedder = EmbeddingService()
    await app.state.embedder.load_model()

    # Pinecone
    from app.services.vector_store import VectorStore
    app.state.vector_store = VectorStore()
    app.state.vector_store.connect()

    # RAG
    from app.services.rag_service import RAGService
    app.state.rag = RAGService(
        embedding_service=app.state.embedder,
        vector_store=app.state.vector_store,
    )
    print("[startup] RAG service ready")

    yield

    await app.state.redis.aclose()
    print("[shutdown] Redis closed")
    await disconnect_mongo()


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
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:3000",
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth routes (no prefix — /login, /me)
app.include_router(auth_router)

# Role routes
app.include_router(super_admin_router)
app.include_router(admin_router)
app.include_router(hr_router)

# Core routes
app.include_router(health.router)
app.include_router(voice.router, prefix=settings.API_PREFIX)