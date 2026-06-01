# backend/app/repositories/leave_repository.py

from datetime import datetime
from app.database.mongo_connection import get_db
from app.models.leave_model import LeaveModel


class LeaveRepository:

    @property
    def collection(self):
        return get_db()["leaves"]

    async def create(self, leave: LeaveModel) -> str:
        """Saves a new leave request. Returns leave_id."""
        await self.collection.insert_one(leave.model_dump())
        return leave.leave_id

    async def find_by_id(self, leave_id: str) -> dict | None:
        return await self.collection.find_one(
            {"leave_id": leave_id},
            {"_id": 0}
        )

    async def find_by_user(self, user_id: str) -> list[dict]:
        """Returns all leave requests for an employee."""
        cursor = self.collection.find(
            {"user_id": user_id},
            {"_id": 0}
        ).sort("applied_at", -1)   # newest first
        return await cursor.to_list(length=50)

    async def find_pending(self) -> list[dict]:
        """Returns all pending requests — used by HR portal."""
        cursor = self.collection.find(
            {"status": "pending"},
            {"_id": 0}
        ).sort("applied_at", 1)    # oldest first — FIFO
        return await cursor.to_list(length=100)

    async def update_status(
        self,
        leave_id: str,
        status: str,
        reviewed_by: str,
        comments: str = None
    ) -> bool:
        result = await self.collection.update_one(
            {"leave_id": leave_id},
            {"$set": {
                "status":      status,
                "reviewed_by": reviewed_by,
                "reviewed_at": datetime.utcnow(),
                "comments":    comments,
            }}
        )
        return result.modified_count > 0