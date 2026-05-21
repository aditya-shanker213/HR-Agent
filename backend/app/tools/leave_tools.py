# backend/app/tools/leave_tools.py

"""
Phase 2: stub tools — return realistic fake data.
Phase 3: these will hit MongoDB via leave_repository.
"""

from datetime import datetime


async def apply_leave(entities: dict, user_id: str = "emp_001") -> dict:
    """
    Applies a leave request.
    entities: {"leave_type": "casual", "num_days": 2, "start_date": "Monday"}
    """
    # Phase 2 stub — pretend it worked
    return {
        "status":       "applied",
        "reference_id": "LV-2025-042",
        "leave_type":   entities.get("leave_type", "casual"),
        "num_days":     entities.get("num_days", 1),
        "start_date":   entities.get("start_date", "Monday"),
        "message":      "Your leave request has been submitted. Your manager will be notified.",
    }


async def get_leave_balance(entities: dict, user_id: str = "emp_001") -> dict:
    """
    Returns the employee's leave balance.
    """
    # Phase 2 stub — hardcoded balances
    all_balances = {
        "casual":    8,
        "sick":      5,
        "earned":    12,
        "emergency": 3,
    }

    leave_type = entities.get("leave_type")
    if leave_type and leave_type in all_balances:
        return {
            "leave_type": leave_type,
            "balance":    all_balances[leave_type],
            "unit":       "days",
        }

    # Return all balances if no specific type asked
    return {"balances": all_balances, "unit": "days"}