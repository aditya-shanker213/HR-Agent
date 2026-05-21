# backend/app/agents/nodes/missing_info.py

from pathlib import Path
from app.agents.state import AgentState
from app.core.config import settings

# Define required fields per intent
# If any of these are absent from state["entities"],
# we must ask the user before proceeding
REQUIRED_FIELDS = {
    "leave_apply":   ["leave_type", "num_days", "start_date"],
    "leave_balance": [],          # no required fields — can ask for all types
    "payroll_query": ["month"],
    "claim_submit":  ["claim_type", "amount"],
}


def _load_prompt() -> str:
    p = Path(settings.PROMPTS_DIR) / "missing_info.txt"
    return p.read_text(encoding="utf-8").strip()


async def missing_info_node(
    state: AgentState,
    ai_service,
) -> AgentState:
    """
    Checks which required fields are missing from state["entities"].
    If fields are missing:
      - sets needs_clarification = True
      - generates a natural question using the LLM
      - puts the question in state["response_text"]
    If all fields present:
      - sets needs_clarification = False
      - graph proceeds to action_dispatcher
    """

    intent = state["intent"]

    # Only transactional intents have required fields
    if intent not in REQUIRED_FIELDS:
        state["needs_clarification"] = False
        return state

    required = REQUIRED_FIELDS[intent]
    present  = set(state["entities"].keys())
    missing  = [f for f in required if f not in present]

    print(f"[missing_info] required: {required} | present: {list(present)} | missing: {missing}")

    if not missing:
        # All fields present — nothing to do
        state["missing_fields"]      = []
        state["needs_clarification"] = False
        return state

    # Fields are missing — generate a clarification question
    state["missing_fields"]      = missing
    state["needs_clarification"] = True

    prompt = _load_prompt()

    question = await ai_service.chat(
        user_message=(
            f"Intent: {intent}\n"
            f"Missing: {missing}"
        ),
        conversation_history=[
            {"role": "system", "content": prompt}
        ],
    )

    state["response_text"] = question.strip()
    print(f"[missing_info] clarification question: {state['response_text']}")

    return state