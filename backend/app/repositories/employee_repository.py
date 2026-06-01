# backend/app/repositories/employee_repository.py

from app.database.mongo_connection import get_db
from app.models.user_model import UserModel


class EmployeeRepository:

    @property
    def collection(self):
        return get_db()["users"]

    async def find_by_id(self, user_id: str) -> dict | None:
        """Find by emp_id or user_id field — handles both document formats."""
        return await self.collection.find_one(
            {"$or": [{"emp_id": user_id}, {"user_id": user_id}]},
            {"_id": 0}
        )

    async def get_leave_balance(self, user_id: str) -> dict | None:
        doc = await self.collection.find_one(
            {"$or": [{"emp_id": user_id}, {"user_id": user_id}]},
            {"leave_balance": 1, "_id": 0}
        )
        return doc.get("leave_balance") if doc else None

    async def deduct_leave(
        self,
        user_id: str,
        leave_type: str,
        num_days: int
    ) -> bool:
        balance = await self.get_leave_balance(user_id)
        if not balance:
            return False
        current = balance.get(leave_type, 0)
        if current < num_days:
            return False
        result = await self.collection.update_one(
            {"$or": [{"emp_id": user_id}, {"user_id": user_id}]},
            {"$inc": {f"leave_balance.{leave_type}": -num_days}}
        )
        return result.modified_count > 0

    async def create_user(self, user: UserModel) -> str:
        await self.collection.insert_one(user.model_dump())
        return user.user_id