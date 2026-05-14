from fastapi import APIRouter, Request
from pydantic import BaseModel
from datetime import datetime, timezone

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    services: dict


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    services = {}

    # Redis
    try:
        await request.app.state.redis.ping()
        services["redis"] = "ok"
    except Exception:
        services["redis"] = "unreachable"

    # Ollama
    try:
        ok = await request.app.state.ai.health_check()
        services["ollama"] = "ok" if ok else "unreachable"
    except Exception:
        services["ollama"] = "unreachable"

    # STT
    try:
        services["stt"] = "ok" if request.app.state.stt.is_loaded() else "not loaded"
    except Exception:
        services["stt"] = "error"

    # TTS
    try:
        services["tts"] = "ok" if request.app.state.tts.is_loaded() else "not loaded"
    except Exception:
        services["tts"] = "error"

    overall = "ok" if all(v == "ok" for v in services.values()) else "degraded"

    return HealthResponse(
        status=overall,
        timestamp=datetime.now(timezone.utc).isoformat(),
        services=services,
    )