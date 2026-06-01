# backend/app/repositories/claim_repository.py

from app.database.mongo_connection import get_db
from app.models.claim_model import ClaimModel


class ClaimRepository:

    @property
    def collection(self):
        return get_db()["claims"]

    async def create(self, claim: ClaimModel) -> str:
        await self.collection.insert_one(claim.model_dump())
        return claim.claim_id

    async def find_by_user(self, user_id: str) -> list[dict]:
        cursor = self.collection.find(
            {"user_id": user_id},
            {"_id": 0}
        ).sort("submitted_at", -1)
        return await cursor.to_list(length=50)

    async def find_pending(self) -> list[dict]:
        cursor = self.collection.find(
            {"status": "pending"},
            {"_id": 0}
        ).sort("submitted_at", 1)
        return await cursor.to_list(length=100)