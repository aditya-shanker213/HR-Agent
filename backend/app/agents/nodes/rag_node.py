# backend/app/agents/nodes/rag_node.py

from pathlib import Path
from app.agents.state import AgentState
from app.core.config import settings


RAG_PROMPT = """You are Aria, an HR assistant for Giggs Software Labs Pvt. Ltd.

Answer the employee's question using ONLY the policy context provided below.
If the answer is not in the context, say: "I don't have specific information about that in our policy. Please contact HR directly."

Be concise — this answer will be spoken aloud. Maximum 3 sentences.
Do not say "according to the context" or "based on the provided text" — just answer naturally.

Policy Context:
{context}

Employee Question: {question}"""


async def rag_node(
    state: AgentState,
    ai_service,
    rag_service=None,
) -> AgentState:
    """
    Real RAG implementation.
    Retrieves relevant policy chunks from Pinecone,
    injects them into the LLM prompt,
    returns a grounded policy answer.
    """

    question = state["transcript"]
    intent   = state.get("intent", "unknown")

    # For unknown/greeting intents — answer naturally without RAG
    if intent == "unknown":
        response = await ai_service.chat(
            user_message=question,
            conversation_history=state.get("conversation_history", []),
        )
        state["response_text"] = response.strip()
        return state

    # If rag_service not available fall back to LLM only
    if rag_service is None:
        print("[rag_node] no rag_service — falling back to LLM only")
        response = await ai_service.chat(
            user_message=question,
            conversation_history=state.get("conversation_history", []),
        )
        state["response_text"] = response.strip()
        return state

    # Retrieve relevant chunks from Pinecone
    chunks = await rag_service.retrieve(question)

    if not chunks:
        # No relevant chunks found
        state["response_text"] = (
            "I don't have specific information about that in our policy. "
            "Please contact HR directly."
        )
        return state

    # Build context from chunks
    context = "\n\n".join([
        f"[{c['section']}]: {c['text']}"
        for c in chunks
    ])

    # Build the grounded prompt
    prompt = RAG_PROMPT.format(
        context=context,
        question=question,
    )

    # Call LLM with grounded context
    response = await ai_service.chat(
        user_message=prompt,
        conversation_history=[],  # RAG answers are self-contained
    )

    state["response_text"] = response.strip()
    print(f"[rag_node] answered using {len(chunks)} policy chunks")

    return state