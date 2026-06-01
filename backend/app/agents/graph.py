# backend/app/agents/graph.py

from app.agents.state import AgentState
from app.agents.context_builder import context_builder_node
from app.agents.nodes.intent_router import intent_router_node
from app.agents.nodes.entity_extractor import entity_extractor_node
from app.agents.nodes.missing_info import missing_info_node
from app.agents.nodes.action_dispatcher import action_dispatcher_node
from app.agents.nodes.rag_node import rag_node
from app.agents.nodes.handoff_node import handoff_node


class AgentGraph:
    """
    The agent graph. Runs nodes in sequence with conditional routing.

    Flow:
      context_builder
           ↓
      intent_router
           ↓
      ┌────┴───────────────────────────┐
    faq/unknown   escalate    transactional
      ↓               ↓            ↓
    rag_node    handoff_node  entity_extractor
                                    ↓
                             missing_info
                            ┌───────┴────────┐
                        missing          complete
                            ↓                ↓
                    clarification    action_dispatcher
                    (return early)
    """

    def __init__(self, ai_service, redis, rag_service=None):
        self.ai      = ai_service
        self.redis   = redis
        self.rag_service = rag_service

    async def run(self, state: AgentState) -> AgentState:

        # ── Node 1: context builder ────────────────────────────────
        # Always runs first. Loads Redis history. Sets all defaults.
        state = await context_builder_node(state, self.redis)

        # ── Node 2: intent router ──────────────────────────────────
        # Classifies what the user wants.
        state = await intent_router_node(state, self.ai)

        intent = state["intent"]
        print(f"[graph] routing intent: {intent}")

        # ── Routing decision ───────────────────────────────────────

        # Branch A: FAQ or unknown → rag_node handles it
        if intent in ("faq", "unknown"):
            state = await rag_node(state, self.ai, self.rag_service)
            return state

        # Branch B: escalate → handoff_node
        if intent == "escalate":
            state = await handoff_node(state)
            return state

        # Branch C: transactional intent
        # (leave_apply, leave_balance, payroll_query, claim_submit)

        # ── Node 3: entity extractor ───────────────────────────────
        # Pull structured data from the transcript
        state = await entity_extractor_node(state, self.ai)

        # ── Node 4: missing info checker ──────────────────────────
        # Are all required fields present?
        state = await missing_info_node(state, self.ai)

        if state["needs_clarification"]:
            # response_text already has the clarification question
            # Return early — do not call any tools
            print(f"[graph] needs clarification — returning question to user")
            return state

        # ── Node 5: action dispatcher ──────────────────────────────
        # All fields present — call the tool and build the response
        state = await action_dispatcher_node(state, self.ai)

        return state