from fastapi import APIRouter, Depends

from app.utils.auth_dependencies import (
    get_current_user
)

from app.services.ai_service import (

    get_employee_context,

    build_ai_context
)

router = APIRouter()


# =========================
# AI CHAT ROUTE
# =========================

@router.post("/ai/chat")
def ai_chat(

    user_query: str,

    current_user: dict = Depends(
        get_current_user
    )
):

    # Fetch employee context
    employee_context = get_employee_context(
        current_user["email"]
    )

    # Build AI context
    ai_context = build_ai_context(

        user_query,

        employee_context
    )

    return {

        "message": "AI context prepared successfully",

        "ai_context": ai_context
    }