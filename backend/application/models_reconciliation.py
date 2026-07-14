"""v2.1 User Confirmation — models."""
from typing import Optional
from sqlmodel import Field, SQLModel
from sqlalchemy import UniqueConstraint
from datetime import datetime


class PlanItemUserDecision(SQLModel, table=True):
    __tablename__ = "plan_item_user_decision"
    __table_args__ = (UniqueConstraint("weekly_plan_item_id", name="uq_item_decision"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    weekly_plan_item_id: int
    user_action: str = "PENDING"
    approved_amount: Optional[float] = None
    reason: str = ""
    user_note: str = ""
    decided_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ExecutionRecord(SQLModel, table=True):
    __tablename__ = "execution_record"
    __table_args__ = (UniqueConstraint("external_reference", name="uq_external_ref"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    weekly_plan_item_id: int
    user_decision_id: Optional[int] = None
    execution_status: str = "PENDING"
    executed_at: Optional[datetime] = None
    actual_amount: Optional[float] = None
    actual_price: Optional[float] = None
    actual_units: Optional[float] = None
    fee: float = 0.0
    platform: str = ""
    external_reference: str = ""
    user_note: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


class ReconciliationRecord(SQLModel, table=True):
    __tablename__ = "reconciliation_record"
    __table_args__ = (UniqueConstraint("execution_record_id", name="uq_execution_reconciliation"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    execution_record_id: int
    reconciliation_status: str = "PENDING"
    planned_amount: Optional[float] = None
    approved_amount: Optional[float] = None
    actual_amount: Optional[float] = None
    amount_variance: Optional[float] = None
    evidence: str = "{}"
    reconciled_at: Optional[datetime] = None
    reconciled_by: str = ""
    transaction_id: Optional[int] = None
