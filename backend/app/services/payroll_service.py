# backend/app/services/payroll_service.py

from app.repositories.payroll_repository import PayrollRepository
from app.repositories.employee_repository import EmployeeRepository


class PayrollService:
    def __init__(self):
        self.payroll_repo = PayrollRepository()
        self.emp_repo     = EmployeeRepository()

    async def get_slip(self, user_id: str, month: str, year: str = None) -> dict:
        """Fetch a specific month's payslip."""
        employee = await self.emp_repo.find_by_id(user_id)
        if not employee:
            return {"status": "error", "message": "Employee not found."}

        slip = await self.payroll_repo.find_slip(user_id, month, year)
        if not slip:
            return {
                "status":  "not_found",
                "message": f"No payslip found for {month}{' ' + year if year else ''}."
            }

        return {"status": "ok", "slip": slip}

    async def get_latest(self, user_id: str) -> dict:
        """Fetch the most recent payslip."""
        slip = await self.payroll_repo.find_latest(user_id)
        if not slip:
            return {"status": "not_found", "message": "No payslip records found."}
        return {"status": "ok", "slip": slip}