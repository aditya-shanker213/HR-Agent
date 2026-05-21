# backend/app/agents/context_builder.py

from app.agents.state import AgentState


async def context_builder_node(
    state: AgentState,
    redis,
) -> AgentState:
    """
    First node in the graph.
    Loads conversation history from Redis into state.
    Sets default values for all fields so later nodes
    never get a KeyError.
    """

    # Load conversation history from Redis
    import json
    raw = await redis.get(f"session:{state['session_id']}:history")
    history = json.loads(raw) if raw else []

    # Set every field to its default value
    # This guarantees no node gets a KeyError
    state["conversation_history"] = history
    state["intent"]               = None
    state["entities"]             = {}
    state["missing_fields"]       = []
    state["response_text"]        = ""
    state["needs_clarification"]  = False
    state["escalate"]             = False
    state["tool_result"]          = None

    return state