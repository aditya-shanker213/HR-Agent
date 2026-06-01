# backend/app/services/claim_service.py

from app.repositories.claim_repository import ClaimRepository
from app.repositories.employee_repository import EmployeeRepository
from app.models.claim_model import ClaimModel


class ClaimService:
    def __init__(self):
        self.claim_repo = ClaimRepository()
        self.emp_repo   = EmployeeRepository()

    async def submit_claim(
        self,
        user_id:     str,
        claim_type:  str,
        amount:      float,
        description: str = None,
        currency:    str = "INR",
    ) -> dict:
        """Submit a reimbursement claim."""
        employee = await self.emp_repo.find_by_id(user_id)
        if not employee:
            return {"status": "error", "message": "Employee not found."}

        claim = ClaimModel(
            user_id     = user_id,
            claim_type  = claim_type,
            amount      = amount,
            currency    = currency,
            description = description,
        )
        claim_id = await self.claim_repo.create(claim)

        return {
            "status":     "submitted",
            "claim_id":   claim_id,
            "claim_type": claim_type,
            "amount":     amount,
            "currency":   currency,
            "message":    "Claim submitted successfully. Pending HR review.",
        }

    async def get_claims(self, user_id: str) -> dict:
        claims = await self.claim_repo.find_by_user(user_id)
        return {"status": "ok", "claims": claims, "count": len(claims)}