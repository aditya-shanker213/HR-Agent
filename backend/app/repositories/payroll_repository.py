# backend/app/repositories/payroll_repository.py

from app.database.mongo_connection import get_db
from app.models.payroll_model import PayrollModel


class PayrollRepository:

    @property
    def collection(self):
        return get_db()["payroll"]

    async def find_slip(self, user_id: str, month: str, year: str = None) -> dict | None:
        """Find a specific month's payslip."""
        query = {"user_id": user_id, "month": month.capitalize()}
        if year:
            query["year"] = year
        return await self.collection.find_one(query, {"_id": 0})

    async def find_latest(self, user_id: str) -> dict | None:
        """Returns the most recent payslip."""
        cursor = self.collection.find(
            {"user_id": user_id},
            {"_id": 0}
        ).sort("created_at", -1).limit(1)
        results = await cursor.to_list(length=1)
        return results[0] if results else None

    async def create(self, payroll: PayrollModel) -> str:
        await self.collection.insert_one(payroll.model_dump())
        return payroll.payroll_id