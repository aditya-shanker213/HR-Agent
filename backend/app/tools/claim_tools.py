# backend/app/tools/claim_tools.py

from app.services.claim_service import ClaimService

_service = ClaimService()


async def submit_claim(entities: dict, user_id: str = "emp_001") -> dict:
    return await _service.submit_claim(
        user_id     = user_id,
        claim_type  = entities.get("claim_type", "other"),
        amount      = float(entities.get("amount", 0)),
        description = entities.get("description"),
    )