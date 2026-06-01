# backend/app/tools/leave_tools.py

from app.services.leave_service import LeaveService

_service = LeaveService()


async def apply_leave(entities: dict, user_id: str = "emp_001") -> dict:
    return await _service.apply_leave(
        user_id    = user_id,
        leave_type = entities.get("leave_type", "casual"),
        num_days   = int(entities.get("num_days", 1)),
        start_date = entities.get("start_date", ""),
        end_date   = entities.get("end_date"),
        reason     = entities.get("reason"),
    )


async def get_leave_balance(entities: dict, user_id: str = "emp_001") -> dict:
    return await _service.get_balance(user_id)