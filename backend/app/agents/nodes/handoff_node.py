# backend/app/agents/nodes/handoff_node.py

from app.agents.state import AgentState


async def handoff_node(
    state: AgentState,
) -> AgentState:
    """
    Phase 6 stub.
    In Phase 6 this will:
      1. create a ticket in MongoDB
      2. fire n8n webhook to notify HR via Slack/email
      3. return ticket reference to employee
    For now — return a holding message.
    """

    state["response_text"] = (
        "I understand. I'm connecting you to the HR team right away. "
        "Someone will follow up with you shortly."
    )
    state["escalate"] = True

    print(f"[handoff_node] stub — Phase 6 will create ticket and fire n8n here")

    return state