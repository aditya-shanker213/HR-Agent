from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator

from ollama import Client

from .config import RAGConfig


class LLMBackendError(RuntimeError):
    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason


class LLMClient(ABC):
    @abstractmethod
    def generate(self, messages: list[dict[str, str]]) -> tuple[str, str | None, float]:
        raise NotImplementedError

    @abstractmethod
    def stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        raise NotImplementedError


class OllamaLLMClient(LLMClient):
    def __init__(self, config: RAGConfig):
        self.config = config
        self.client = Client(host=config.ollama_base_url)

    @staticmethod
    def looks_like_reasoning(text: str) -> bool:
        cleaned = text.strip().lower()
        return cleaned.startswith(
            (
                "hmm",
                "okay",
                "ok,",
                "so the user",
                "the user",
                "user wants",
                "let me",
                "i need",
                "i should",
                "looking at",
                "based solely",
                "first,",
                "we need",
            )
        )

    @staticmethod
    def _message_value(message: object, key: str) -> str:
        if message is None:
            return ""
        if hasattr(message, "get"):
            return message.get(key, "") or ""  # type: ignore[attr-defined]
        return getattr(message, key, "") or ""

    def generate(self, messages: list[dict[str, str]]) -> tuple[str, str | None, float]:
        started = time.perf_counter()
        try:
            response = self.client.chat(
                model=self.config.ollama_model,
                messages=messages,
                stream=False,
                think=False,
                options=self.config.ollama_options,
                keep_alive="10m",
            )
        except ConnectionError as exc:
            raise LLMBackendError(
                "Failed to connect to Ollama. Start Ollama and verify the selected model is installed.",
                "ollama_connection_error",
            ) from exc

        message = response.get("message", {}) if hasattr(response, "get") else getattr(response, "message", None)
        answer = self._message_value(message, "content").strip()
        done_reason = response.get("done_reason", None) if hasattr(response, "get") else getattr(response, "done_reason", None)
        if self.looks_like_reasoning(answer):
            return "", "reasoning_detected", time.perf_counter() - started
        return answer, done_reason, time.perf_counter() - started

    def stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        pending_text = ""
        released = False
        started = time.perf_counter()
        try:
            response_stream = self.client.chat(
                model=self.config.ollama_model,
                messages=messages,
                stream=True,
                think=False,
                options=self.config.ollama_options,
                keep_alive="10m",
            )
        except ConnectionError as exc:
            raise LLMBackendError(
                "Failed to connect to Ollama. Start Ollama and verify the selected model is installed.",
                "ollama_connection_error",
            ) from exc

        for chunk in response_stream:
            message = chunk.get("message", {}) if hasattr(chunk, "get") else getattr(chunk, "message", None)
            delta = self._message_value(message, "content")
            if not delta:
                continue
            if released:
                yield delta
                continue
            pending_text += delta
            if self.looks_like_reasoning(pending_text):
                return
            if len(pending_text.strip()) >= 40 or re.search(r"[.!?]\s$", pending_text):
                released = True
                yield pending_text
                pending_text = ""
            if time.perf_counter() - started > self.config.max_generation_seconds:
                return
        if pending_text and not self.looks_like_reasoning(pending_text):
            yield pending_text


def build_llm_client(config: RAGConfig) -> LLMClient:
    provider = config.llm_provider.lower()
    if provider != "ollama":
        raise ValueError(f"Unsupported LLM_PROVIDER={config.llm_provider!r}. Use LLM_PROVIDER=ollama.")
    return OllamaLLMClient(config)
