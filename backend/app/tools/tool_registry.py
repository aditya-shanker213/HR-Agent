# backend/app/tools/tool_registry.py

"""
Maps intent strings to tool functions.
action_dispatcher looks up the intent here and calls the right function.
Adding a new capability = add one entry here.
"""

from app.tools.leave_tools import apply_leave, get_leave_balance

TOOL_REGISTRY = {
    "leave_apply":   apply_leave,
    "leave_balance": get_leave_balance,
    # Phase 3 will add:
    # "payroll_query":  get_payslip,
    # "claim_submit":   submit_claim,
}


async def dispatch(intent: str, entities: dict, user_id: str = "emp_001") -> dict:
    """
    Looks up the tool for the given intent and calls it.
    Returns the tool's result dict.
    Returns an error dict if no tool is registered.
    """
    tool_fn = TOOL_REGISTRY.get(intent)

    if not tool_fn:
        return {
            "status":  "no_tool",
            "message": f"No tool registered for intent: {intent}",
        }

    result = await tool_fn(entities=entities, user_id=user_id)
    print(f"[tool_registry] dispatched {intent} → result: {result}")
    return result