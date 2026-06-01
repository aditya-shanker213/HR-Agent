# backend/app/models/payroll_model.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class DeductionBreakdown(BaseModel):
    """Embedded — stored inside payroll document."""
    pf:          float = 0.0   # provident fund
    tax:         float = 0.0   # income tax
    professional_tax: float = 0.0
    other:       float = 0.0


class PayrollModel(BaseModel):
    """
    Represents one month's salary record.
    One document per employee per month.
    """
    payroll_id:   str = Field(default_factory=lambda: f"PAY-{uuid.uuid4().hex[:8].upper()}")
    user_id:      str
    month:        str            # e.g. "March"
    year:         str            # e.g. "2025"
    basic_salary: float
    allowances:   float = 0.0
    deductions:   DeductionBreakdown = Field(default_factory=DeductionBreakdown)
    net_salary:   float
    paid_on:      Optional[datetime] = None
    created_at:   datetime = Field(default_factory=datetime.utcnow)

import uuid  # add at top of file