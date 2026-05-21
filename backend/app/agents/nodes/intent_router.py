# backend/app/agents/nodes/intent_router.py

from pathlib import Path
from app.agents.state import AgentState
from app.core.config import settings

# Valid intents — if LLM returns anything else we treat it as unknown
VALID_INTENTS = {
    "leave_apply",
    "leave_balance",
    "payroll_query",
    "claim_submit",
    "faq",
    "escalate",
    "unknown",
}


def _load_prompt() -> str:
    p = Path(settings.PROMPTS_DIR) / "intent_router.txt"
    return p.read_text(encoding="utf-8").strip()


async def intent_router_node(
    state: AgentState,
    ai_service,
) -> AgentState:
    """
    Reads the transcript.
    Asks the LLM to classify it into one intent.
    Writes the intent back into state.
    """

    prompt = _load_prompt()

    # We give the LLM the system prompt + one user message
    # The user message contains the transcript
    # We use conversation_history=[] here intentionally —
    # intent classification should be based on the current
    # transcript only, not influenced by previous turns
    response = await ai_service.chat(
        user_message=f"Transcript: \"{state['transcript']}\"",
        conversation_history=[
            {"role": "system", "content": prompt}
        ],
    )

    # Clean the response — LLMs sometimes add spaces or newlines
    intent = response.strip().lower().replace('"', '').replace("'", "")

    # Validate — if the LLM returns garbage, default to unknown
    if intent not in VALID_INTENTS:
        print(f"[intent_router] Unexpected intent: '{intent}' — defaulting to unknown")
        intent = "unknown"

    print(f"[intent_router] '{state['transcript']}' → intent: {intent}")

    state["intent"] = intent
    return state