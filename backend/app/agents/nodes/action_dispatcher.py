# backend/app/agents/nodes/action_dispatcher.py

from app.agents.state import AgentState
from app.tools.tool_registry import dispatch


# Template for turning tool results into spoken responses
RESPONSE_PROMPT = """
You are Aria, an HR voice assistant.
A tool was called and returned a result.
Convert the result into a single natural spoken sentence or two.
Be concise — this will be spoken aloud.
Do not mention "tool" or "function" or "result".
Sound like a helpful HR assistant confirming what was done.
"""


async def action_dispatcher_node(
    state: AgentState,
    ai_service,
) -> AgentState:
    """
    Calls the right tool based on intent + entities.
    Then asks LLM to convert the raw result into natural speech.
    Writes the final spoken response to state["response_text"].
    """

    intent   = state["intent"]
    entities = state["entities"]

    # Call the tool
    tool_result = await dispatch(
        intent=intent,
        entities=entities,
        user_id="emp_001",   # Phase 3: replace with real user from JWT
    )

    state["tool_result"] = tool_result

    # Convert tool result to natural language
    response = await ai_service.chat(
        user_message=(
            f"Intent was: {intent}\n"
            f"Entities: {entities}\n"
            f"Tool result: {tool_result}"
        ),
        conversation_history=[
            {"role": "system", "content": RESPONSE_PROMPT}
        ],
    )

    state["response_text"] = response.strip()
    print(f"[action_dispatcher] response: {state['response_text']}")

    return state