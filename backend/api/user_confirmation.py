"""v2.1 User Confirmation — final ledger gate."""
from decimal import Decimal
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, field_validator


class DecisionRequest(BaseModel):
    user_action: Literal["APPROVED", "SKIPPED", "DEFERRED", "CANCELLED"]
    approved_amount: Optional[float] = None
    reason: str = ""
    user_note: str = ""


class ExecutionRequest(BaseModel):
    execution_status: Literal["PENDING", "EXECUTED", "FAILED", "CANCELLED"]
    actual_amount: Optional[float] = None
    actual_price: Optional[float] = None
    actual_units: Optional[float] = None
    fee: float = 0.0
    platform: str = ""
    external_reference: str = ""
    executed_at: Optional[str] = None
    user_note: str = ""


class ReconciliationRequest(BaseModel):
    confirm: bool = False
