# backend/app/routes/voice.py

import json
import uuid
from fastapi import APIRouter, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import Response

from app.agents.state import AgentState
from app.agents.graph import AgentGraph
from app.core.config import settings

router = APIRouter(prefix="/voice", tags=["voice"])

MAX_HISTORY_TURNS = 10


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


@router.post("/chat")
async def voice_chat(
    request: Request,
    audio: UploadFile = File(...),
    session_id: str = Form(default=None),
):
    if not session_id:
        session_id = str(uuid.uuid4())

    redis = request.app.state.redis
    stt   = request.app.state.stt
    tts   = request.app.state.tts
    ai    = request.app.state.ai

    # ── STT ──────────────────────────────────────────────────
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(400, "Empty audio.")

    try:
        transcript = await stt.transcribe(audio_bytes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, f"STT error: {e}")

    # ── Agent graph ───────────────────────────────────────────
    # Build the initial state with just what we know right now.
    # context_builder_node fills the rest.
    initial_state: AgentState = {
        "session_id":            session_id,
        "transcript":            transcript,
        "conversation_history":  [],
        "intent":                None,
        "entities":              {},
        "missing_fields":        [],
        "response_text":         "",
        "needs_clarification":   False,
        "escalate":              False,
        "tool_result":           None,
    }

    graph = AgentGraph(ai_service=ai, redis=redis)

    try:
        result_state = await graph.run(initial_state)
    except Exception as e:
        raise HTTPException(500, f"Agent error: {e}")

    response_text = result_state["response_text"]

    # Fallback if graph produced no response
    if not response_text:
        response_text = "I'm sorry, I didn't understand that. Could you rephrase?"

    # ── Save conversation history ─────────────────────────────
    history = await _get_history(redis, session_id)
    history += [
        {"role": "user",      "content": transcript},
        {"role": "assistant", "content": response_text},
    ]
    await _save_history(redis, session_id, history)

    # ── TTS ───────────────────────────────────────────────────
    try:
        audio_out = await tts.synthesize(response_text)
    except Exception as e:
        raise HTTPException(500, f"TTS error: {e}")

    return Response(
        content=audio_out,
        media_type="audio/wav",
        headers={
            "X-Session-ID":    session_id,
            "X-Transcript":    transcript,
            "X-Response-Text": response_text,
            "X-Intent":        result_state.get("intent") or "unknown",
            "Access-Control-Expose-Headers":
                "X-Session-ID, X-Transcript, X-Response-Text, X-Intent",
        },
    )


@router.delete("/chat/{session_id}")
async def clear_session(session_id: str, request: Request):
    await request.app.state.redis.delete(f"session:{session_id}:history")
    return {"cleared": True, "session_id": session_id}