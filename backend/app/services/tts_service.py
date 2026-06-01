import asyncio
import io
import os
import tempfile
from typing import Optional
import numpy as np
import soundfile as sf

from app.core.config import settings


class TTSService:
    def __init__(self):
        self._kokoro = None

    def is_loaded(self) -> bool:
        return self._kokoro is not None

    async def load_model(self) -> None:
        loop = asyncio.get_event_loop()

        def _load():
            from kokoro_onnx import Kokoro
            # Model files auto-download on first use (~330 MB, cached after)
            return Kokoro("kokoro-v0_19.onnx", "voices.bin")

        self._kokoro = await loop.run_in_executor(None, _load)

    async def synthesize(self, text: str) -> bytes:
        if not self._kokoro:
            raise RuntimeError("TTS not loaded.")
        if not text.strip():
            raise ValueError("Empty text.")

        # Keep responses concise for voice
        if len(text) > 500:
            text = text[:500].rsplit(" ", 1)[0] + "."

        loop = asyncio.get_event_loop()

        def _run():
            # Auto-detect voice if configured one isn't available

            available = list(self._kokoro.get_voices())
            preferred = ["af_sarah", "af_sky", "af_bella", "af"]
            voice = next((v for v in preferred if v in available), available[0])
            


            samples, sample_rate = self._kokoro.create(
                text,
                voice=voice,
                speed=1.0,
                lang="en-us",
            )
            buf = io.BytesIO()
            sf.write(buf, samples, sample_rate, format="WAV")
            buf.seek(0)
            return buf.read()

        return await loop.run_in_executor(None, _run)
        