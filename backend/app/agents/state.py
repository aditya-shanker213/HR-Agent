# backend/app/agents/state.py

from typing import TypedDict, Optional


class AgentState(TypedDict):
    """
    The single object that flows through every node in the agent graph.
    Each node reads some fields and writes some fields.
    No node communicates with another node directly — only through this.
    """
    user_id: str   # ← ADD — real user from JWT, replaces hardcoded emp_001

    # ── Set at the start of every request ─────────────────────────
    session_id:   str            # Redis key for conversation history
    transcript:   str            # raw text from Whisper STT
                                 # e.g. "I want 2 days casual leave from Monday"

    # ── Filled by context_builder ──────────────────────────────────
    conversation_history: list   # last N turns loaded from Redis
                                 # e.g. [{"role":"user","content":"..."},...]

    # ── Filled by intent_router ────────────────────────────────────
    intent: Optional[str]        # one of:
                                 # "leave_apply"
                                 # "leave_balance"
                                 # "payroll_query"
                                 # "claim_submit"
                                 # "faq"
                                 # "escalate"
                                 # "unknown"

    # ── Filled by entity_extractor ─────────────────────────────────
    entities: dict               # extracted fields from transcript
                                 # for leave_apply:
                                 #   {"leave_type": "casual",
                                 #    "num_days": 2,
                                 #    "start_date": "Monday"}
                                 # for payroll_query:
                                 #   {"month": "March", "year": "2025"}

    # ── Filled by missing_info_checker ─────────────────────────────
    missing_fields: list[str]    # required fields that are absent
                                 # e.g. ["start_date", "leave_type"]
                                 # empty list = all fields present

    # ── Filled by action_dispatcher or rag_node ────────────────────
    response_text: str           # the final text Aria will speak
                                 # e.g. "Done. Applied 2 days casual
                                 #        leave from Monday."

    # ── Control flags ──────────────────────────────────────────────
    needs_clarification: bool    # True  = missing_info node found gaps
                                 #         → ask user, don't call tools
                                 # False = all info present → proceed

    escalate: bool               # True  = handoff_node should fire
                                 #         → create ticket, notify HR
                                 # False = agent handles it

    # ── Tool result ────────────────────────────────────────────────
    tool_result: Optional[dict]  # raw result from tool call
                                 # e.g. {"status": "applied",
                                 #        "reference": "LV-2025-042"}
                                 # None if no tool was called yet