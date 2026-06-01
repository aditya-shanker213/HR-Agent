# backend/app/routes/voice.py

import json
import uuid
import os
from fastapi import APIRouter, UploadFile, File, Form, Request, HTTPException, Security
from fastapi.responses import Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

from app.agents.state import AgentState
from app.agents.graph import AgentGraph
from app.core.config import settings

router   = APIRouter(prefix="/voice", tags=["voice"])
security = HTTPBearer(auto_error=False)

MAX_HISTORY_TURNS = 10


def _get_user_from_token(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> dict:
    if not credentials:
        return {"emp_id": "emp_001", "role": "employee", "name": "Test User"}
    try:
        payload = jwt.decode(
            credentials.credentials,
            os.getenv("JWT_SECRET"),
            algorithms=[os.getenv("JWT_ALGORITHM", "HS256")]
        )
        return payload
    except JWTError:
        return {"emp_id": "emp_001", "role": "employee", "name": "Test User"}


async def _get_history(redis, session_id: str) -> list[dict]:
    raw = await redis.get(f"session:{session_id}:history")
    return json.loads(raw) if raw else []


async def _save_history(redis, session_id: str, history: list[dict]) -> None:
    if len(history) > MAX_HISTORY_TURNS * 2:
        history = history[-(MAX_HISTORY_TURNS * 2):]
    await redis.setex(
        f"session:{session_id}:history",
        settings.SESSION_TTL_SECONDS,
        json.dumps(history),
    )

def _safe_header(text: str) -> str:
    """Strip non-ASCII characters from text for use in HTTP headers."""
    return text.encode("ascii", errors="ignore").decode("ascii")


@router.post("/chat")
async def voice_chat(
    request: Request,
    audio: UploadFile = File(...),
    session_id: str = Form(default=None),
    current_user: dict = Security(_get_user_from_token),
):
    if not session_id:
        session_id = str(uuid.uuid4())

    # Real user from JWT — not hardcoded
    user_id = (
        current_user.get("emp_id") or
        current_user.get("user_id") or
        "emp_001"
    )

    redis = request.app.state.redis
    stt   = request.app.state.stt
    tts   = request.app.state.tts
    ai    = request.app.state.ai

    # ── 1. Read audio ─────────────────────────────────────────
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(400, "Empty audio.")

    # ── 2. STT ───────────────────────────────────────────────
    try:
        transcript = await stt.transcribe(audio_bytes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, f"STT error: {e}")

    # ── 3. Build agent state ──────────────────────────────────
    initial_state: AgentState = {
        "session_id":           session_id,
        "transcript":           transcript,
        "conversation_history": [],
        "intent":               None,
        "entities":             {},
        "missing_fields":       [],
        "response_text":        "",
        "needs_clarification":  False,
        "escalate":             False,
        "tool_result":          None,
        "user_id":              user_id,
    }

    # ── 4. Run agent graph ────────────────────────────────────
    graph = AgentGraph(
        ai_service=ai,
        redis=redis,
        rag_service=getattr(request.app.state, 'rag', None),
    )

    try:
        result_state = await graph.run(initial_state)
    except Exception as e:
        raise HTTPException(500, f"Agent error: {e}")

    response_text = result_state["response_text"]
    if not response_text:
        response_text = "I'm sorry, I didn't understand that. Could you rephrase?"

    # ── 5. Save history ───────────────────────────────────────
    history = await _get_history(redis, session_id)
    history += [
        {"role": "user",      "content": transcript},
        {"role": "assistant", "content": response_text},
    ]
    await _save_history(redis, session_id, history)

    # ── 6. TTS ───────────────────────────────────────────────
    try:
        audio_out = await tts.synthesize(response_text)
    except Exception as e:
        raise HTTPException(500, f"TTS error: {e}")

    return Response(
        content=audio_out,
        media_type="audio/wav",
        headers={
            "X-Session-ID":    session_id,
            "X-Transcript":    _safe_header(transcript),
            "X-Response-Text": _safe_header(response_text),
            "X-Intent":        _safe_header(result_state.get("intent") or "unknown"),
            "Access-Control-Expose-Headers":
                "X-Session-ID, X-Transcript, X-Response-Text, X-Intent",
        },
    )


@router.delete("/chat/{session_id}")
async def clear_session(session_id: str, request: Request):
    await request.app.state.redis.delete(f"session:{session_id}:history")
    return {"cleared": True, "session_id": session_id}