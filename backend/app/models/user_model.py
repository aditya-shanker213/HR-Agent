# backend/app/models/user_model.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class LeaveBalance(BaseModel):
    """Embedded document — stored inside the user document."""
    casual:    int = 12
    sick:      int = 8
    earned:    int = 15
    emergency: int = 3


class UserModel(BaseModel):
    """
    Represents one employee in the users collection.
    Every leave/payroll/claim operation references user_id.
    """
    user_id:        str              # e.g. "emp_001"
    name:           str              # e.g. "Aditya"
    email:          str
    department:     str              # e.g. "Engineering"
    role:           str = "employee" # employee | hr | admin
    manager_id:     Optional[str] = None
    leave_balance:  LeaveBalance = Field(default_factory=LeaveBalance)
    joining_date:   datetime = Field(default_factory=datetime.utcnow)
    is_active:      bool = True
    created_at:     datetime = Field(default_factory=datetime.utcnow)