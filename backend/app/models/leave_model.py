# backend/app/models/leave_model.py

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
import uuid


class LeaveModel(BaseModel):
    """
    Represents one leave request in the leaves collection.
    Status flows: pending → approved | rejected
    """
    leave_id:    str = Field(default_factory=lambda: f"LV-{uuid.uuid4().hex[:8].upper()}")
    user_id:     str                        # who applied
    leave_type:  Literal["casual", "sick", "earned", "emergency"]
    num_days:    int
    start_date:  str                        # stored as string — Phase 5 adds date parsing
    end_date:    Optional[str] = None
    reason:      Optional[str] = None
    status:      Literal["pending", "approved", "rejected"] = "pending"
    applied_at:  datetime = Field(default_factory=datetime.utcnow)
    reviewed_by: Optional[str] = None      # HR user_id who approved/rejected
    reviewed_at: Optional[datetime] = None
    comments:    Optional[str] = None      # HR comments on rejection