# backend/app/tools/tool_registry.py

from app.tools.leave_tools import apply_leave, get_leave_balance
from app.tools.payroll_tools import get_payslip
from app.tools.claim_tools import submit_claim


TOOL_REGISTRY = {
    "leave_apply":   apply_leave,
    "leave_balance": get_leave_balance,
    "payroll_query": get_payslip,
    "claim_submit":  submit_claim,
}


async def dispatch(intent: str, entities: dict, user_id: str = "emp_001") -> dict:
    tool_fn = TOOL_REGISTRY.get(intent)
    if not tool_fn:
        return {"status": "no_tool", "message": f"No tool for intent: {intent}"}
    result = await tool_fn(entities=entities, user_id=user_id)
    print(f"[tool_registry] dispatched {intent} → {result}")
    return result