# backend/app/models/claim_model.py

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
import uuid


class ClaimModel(BaseModel):
    """
    Represents one reimbursement claim.
    Status flows: pending → approved | rejected
    """
    claim_id:    str = Field(default_factory=lambda: f"CL-{uuid.uuid4().hex[:8].upper()}")
    user_id:     str
    claim_type:  Literal["travel", "food", "accommodation", "medical", "other"]
    amount:      float
    currency:    str = "INR"
    description: Optional[str] = None
    status:      Literal["pending", "approved", "rejected"] = "pending"
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_by:  Optional[str] = None
    reviewed_at:  Optional[datetime] = None