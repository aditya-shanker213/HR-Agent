import json
import uuid
from fastapi import APIRouter, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import Response

from app.core.config import settings

router = APIRouter(prefix="/voice", tags=["voice"])

MAX_HISTORY_TURNS = 10


async def _get_history(redis, session_id: str) -> list[dict]:
    raw = await redis.get(f"session:{session_id}:history")
    if not raw:
        return []
    return json.loads(raw)


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

    redis   = request.app.state.redis
    stt     = request.app.state.stt
    ai      = request.app.state.ai
    tts     = request.app.state.tts

    # Read audio
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(400, "Empty audio file.")
    if len(audio_bytes) > settings.MAX_AUDIO_SIZE_BYTES:
        raise HTTPException(413, "Audio file too large.")

    # STT
    try:
        transcript = await stt.transcribe(audio_bytes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, f"Transcription error: {e}")

    # History
    history = await _get_history(redis, session_id)

    # LLM
    try:
        response_text = await ai.chat(
            user_message=transcript,
            conversation_history=history,
        )
    except TimeoutError:
        raise HTTPException(504, "LLM timed out. Try a shorter question.")
    except Exception as e:
        raise HTTPException(500, f"AI error: {e}")

    # Save history
    history += [
        {"role": "user",      "content": transcript},
        {"role": "assistant", "content": response_text},
    ]
    await _save_history(redis, session_id, history)

    # TTS
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
            "Access-Control-Expose-Headers":
                "X-Session-ID, X-Transcript, X-Response-Text",
        },
    )


@router.delete("/chat/{session_id}")
async def clear_session(session_id: str, request: Request):
    await request.app.state.redis.delete(f"session:{session_id}:history")
    return {"cleared": True, "session_id": session_id}