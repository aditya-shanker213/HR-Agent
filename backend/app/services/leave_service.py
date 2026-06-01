# backend/app/services/leave_service.py

from app.repositories.leave_repository import LeaveRepository
from app.repositories.employee_repository import EmployeeRepository
from app.models.leave_model import LeaveModel


class LeaveService:
    def __init__(self):
        self.leave_repo = LeaveRepository()
        self.emp_repo   = EmployeeRepository()

    async def apply_leave(
        self,
        user_id:    str,
        leave_type: str,
        num_days:   int,
        start_date: str,
        end_date:   str = None,
        reason:     str = None,
    ) -> dict:
        """
        Full leave application flow:
        1. Check employee exists
        2. Check sufficient balance
        3. Deduct balance
        4. Save leave record
        5. Return result
        """

        # 1. Check employee exists
        employee = await self.emp_repo.find_by_id(user_id)
        if not employee:
            return {"status": "error", "message": "Employee not found."}

        # 2. Check balance
        balance = await self.emp_repo.get_leave_balance(user_id)
        available = balance.get(leave_type, 0) if balance else 0

        if available < num_days:
            return {
                "status":  "error",
                "message": f"Insufficient {leave_type} leave balance. "
                           f"You have {available} days but requested {num_days}."
            }

        # 3. Deduct balance
        deducted = await self.emp_repo.deduct_leave(user_id, leave_type, num_days)
        if not deducted:
            return {"status": "error", "message": "Failed to update leave balance."}

        # 4. Save leave record
        leave = LeaveModel(
            user_id    = user_id,
            leave_type = leave_type,
            num_days   = num_days,
            start_date = start_date,
            end_date   = end_date,
            reason     = reason,
        )
        leave_id = await self.leave_repo.create(leave)

        # 5. Return success
        return {
            "status":       "applied",
            "leave_id":     leave_id,
            "leave_type":   leave_type,
            "num_days":     num_days,
            "start_date":   start_date,
            "message":      "Leave applied successfully. Pending manager approval.",
        }

    async def get_balance(self, user_id: str) -> dict:
        """Returns the employee's current leave balance."""
        balance = await self.emp_repo.get_leave_balance(user_id)
        if not balance:
            return {"status": "error", "message": "Employee not found."}
        return {"status": "ok", "balance": balance}

    async def get_history(self, user_id: str) -> dict:
        """Returns all leave requests for the employee."""
        leaves = await self.leave_repo.find_by_user(user_id)
        return {"status": "ok", "leaves": leaves, "count": len(leaves)}