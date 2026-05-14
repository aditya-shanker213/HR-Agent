import httpx
from pathlib import Path
from typing import Optional
from app.core.config import settings


class AIService:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS)

    def _load_prompt(self) -> str:
        p = Path(settings.PROMPTS_DIR) / "system_prompt.txt"
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
        return (
            "You are Aria, an AI HR assistant. Help employees with leave, "
            "payroll, claims, and policy questions. Be concise — responses "
            "should be under 3 sentences since they are spoken aloud."
        )

    async def health_check(self) -> bool:
        try:
            r = await self._client.get(
                f"{settings.OLLAMA_BASE_URL}/api/tags",
                timeout=5.0,
            )
            if r.status_code != 200:
                return False
            models = [m["name"] for m in r.json().get("models", [])]
            return any(settings.OLLAMA_MODEL.split(":")[0] in m for m in models)
        except Exception:
            return False

    async def chat(
        self,
        user_message: str,
        conversation_history: Optional[list[dict]] = None,
    ) -> str:
        messages = [
            {"role": "system", "content": self._load_prompt()},
            *(conversation_history or []),
            {"role": "user", "content": user_message},
        ]
        try:
            r = await self._client.post(
                f"{settings.OLLAMA_BASE_URL}/v1/chat/completions",
                json={
                    "model":       settings.OLLAMA_MODEL,
                    "messages":    messages,
                    "temperature": settings.LLM_TEMPERATURE,
                    "max_tokens":  settings.LLM_MAX_TOKENS,
                    "stream":      False,
                },
            )
            r.raise_for_status()
        except httpx.TimeoutException:
            raise TimeoutError("Ollama did not respond in time.")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Ollama error {e.response.status_code}")

        return r.json()["choices"][0]["message"]["content"].strip()