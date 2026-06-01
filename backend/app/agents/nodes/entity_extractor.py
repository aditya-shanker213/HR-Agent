# backend/app/agents/nodes/entity_extractor.py

import json
from pathlib import Path
from app.agents.state import AgentState
from app.core.config import settings


def _load_prompt() -> str:
    p = Path(settings.PROMPTS_DIR) / "entity_extractor.txt"
    return p.read_text(encoding="utf-8").strip()


def _clean_json(raw: str) -> str:
    """Strip think tags, markdown fences, and fix common LLM JSON errors."""
    import re
    # Remove qwen3 think blocks
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL)
    raw = raw.strip()
    # Remove markdown fences
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1])
    raw = raw.strip()
    # Fix trailing commas before } or ] — common LLM mistake
    raw = re.sub(r',\s*([}\]])', r'\1', raw)
    # Fix trailing null values like {..., null}
    raw = re.sub(r',\s*null\s*}', '}', raw)
    raw = re.sub(r',\s*null\s*]', ']', raw)
    return raw.strip()


async def entity_extractor_node(
    state: AgentState,
    ai_service,
) -> AgentState:
    """
    Reads the transcript and intent from state.
    Asks the LLM to extract structured entities as JSON.
    Writes the entities dict back into state.

    Only runs for transactional intents — not for faq or unknown.
    """

    intent = state["intent"]

    # These intents don't need entity extraction
    if intent in ("faq", "unknown", "escalate", None):
        return state

    prompt = _load_prompt()

    response = await ai_service.chat(
        user_message=(
            f"Intent: {intent}\n"
            f"Transcript: \"{state['transcript']}\""
        ),
        conversation_history=[
            {"role": "system", "content": prompt}
        ],
    )

    # Parse JSON safely
    try:
        cleaned = _clean_json(response)
        entities = json.loads(cleaned)

        # Ensure it's a dict — LLM could return a list by mistake
        if not isinstance(entities, dict):
            raise ValueError("Expected a dict")

    except (json.JSONDecodeError, ValueError) as e:
        print(f"[entity_extractor] JSON parse failed: {e} | raw: {response}")
        entities = {}

    # Remove null values — missing_info checker handles those
    entities = {k: v for k, v in entities.items() if v is not None}

    print(f"[entity_extractor] entities: {entities}")

    state["entities"] = entities
    return state