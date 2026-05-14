import asyncio
import tempfile
import os
from typing import Optional
from faster_whisper import WhisperModel
from app.core.config import settings


class STTService:
    def __init__(self):
        self._model: Optional[WhisperModel] = None

    def is_loaded(self) -> bool:
        return self._model is not None

    async def load_model(self) -> None:
        loop = asyncio.get_event_loop()
        self._model = await loop.run_in_executor(
            None,
            lambda: WhisperModel(
                settings.WHISPER_MODEL_SIZE,
                device=settings.WHISPER_DEVICE,
                compute_type=settings.WHISPER_COMPUTE_TYPE,
            ),
        )

    async def transcribe(self, audio_bytes: bytes, language: str = "en") -> str:
        if not self._model:
            raise RuntimeError("STT model not loaded.")
        if not audio_bytes:
            raise ValueError("Empty audio.")
        if len(audio_bytes) > settings.MAX_AUDIO_SIZE_BYTES:
            raise ValueError("Audio too large.")

        loop = asyncio.get_event_loop()

        def _run():
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                tmp = f.name
            try:
                segments, _ = self._model.transcribe(
                    tmp,
                    language=language,
                    beam_size=5,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 500},
                )
                return " ".join(s.text.strip() for s in segments).strip()
            finally:
                os.unlink(tmp)

        text = await loop.run_in_executor(None, _run)
        if not text:
            raise ValueError("No speech detected. Please speak clearly.")
        return text