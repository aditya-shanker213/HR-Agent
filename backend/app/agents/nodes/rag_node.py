# backend/app/agents/nodes/rag_node.py

from app.agents.state import AgentState


async def rag_node(
    state: AgentState,
    ai_service,
) -> AgentState:
    """
    Phase 4 stub.
    In Phase 4 this will:
      1. embed the transcript
      2. search Pinecone for relevant policy chunks
      3. inject chunks into LLM prompt
      4. return grounded policy answer
    For now — use the LLM with just the system prompt.
    """

    # Stub: just let the LLM answer from its training
    response = await ai_service.chat(
        user_message=state["transcript"],
        conversation_history=state["conversation_history"],
    )

    state["response_text"] = response.strip()
    print(f"[rag_node] stub response (Phase 4 will add Pinecone here)")

    return state