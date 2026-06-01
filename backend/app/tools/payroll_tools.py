# backend/app/tools/payroll_tools.py

from app.services.payroll_service import PayrollService

_service = PayrollService()


async def get_payslip(entities: dict, user_id: str = "emp_001") -> dict:
    month = entities.get("month")
    year  = entities.get("year")

    if month:
        return await _service.get_slip(user_id, month, year)
    return await _service.get_latest(user_id)