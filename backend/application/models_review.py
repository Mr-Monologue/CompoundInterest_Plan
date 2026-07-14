"""v2.1 Minimal Review Domain Models."""
from typing import Optional
from sqlmodel import Field, SQLModel
from sqlalchemy import UniqueConstraint
from datetime import datetime


class WeeklyReview(SQLModel, table=True):
    __tablename__ = "weekly_review"
    __table_args__ = (UniqueConstraint("weekly_plan_id", name="uq_review_plan"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    weekly_plan_id: int
    period_start: str = ""
    period_end: str = ""
    status: str = "DRAFT"
    strategy_version: str = ""
    planned_total: float = 0.0
    approved_total: float = 0.0
    actual_total: float = 0.0
    matched_total: float = 0.0
    unexecuted_total: float = 0.0
    approval_variance_total: Optional[float] = None
    execution_variance_total: Optional[float] = None
    plan_execution_variance_total: Optional[float] = None
    item_count: int = 0
    approved_count: int = 0
    executed_count: int = 0
    matched_count: int = 0
    mismatch_count: int = 0
    skipped_count: int = 0
    deferred_count: int = 0
    cancelled_count: int = 0
    blocked_count: int = 0
    undecided_count: int = 0
    data_quality_findings_json: str = "{}"
    risk_findings_json: str = "{}"
    exposure_findings_json: str = "{}"
    process_findings_json: str = "{}"
    user_overall_note: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    generated_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class WeeklyReviewItem(SQLModel, table=True):
    __tablename__ = "weekly_review_item"
    __table_args__ = (UniqueConstraint("weekly_review_id", "weekly_plan_item_id", name="uq_review_item"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    weekly_review_id: int
    weekly_plan_item_id: int
    asset_code: str = ""
    asset_role: str = "core"
    plan_action: str = ""
    planned_amount: Optional[float] = None
    user_action: str = ""
    approved_amount: Optional[float] = None
    decision_reason: str = ""
    decision_note: str = ""
    execution_status: str = ""
    actual_amount: Optional[float] = None
    actual_price: Optional[float] = None
    actual_units: Optional[float] = None
    execution_note: str = ""
    reconciliation_status: str = ""
    approval_variance: Optional[float] = None
    execution_variance: Optional[float] = None
    plan_execution_variance: Optional[float] = None
    review_category: str = "UNDECIDED"
    exception_codes_json: str = "[]"
    facts_json: str = "{}"
    user_variance_reason: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class FollowUpAction(SQLModel, table=True):
    __tablename__ = "follow_up_action"
    id: Optional[int] = Field(default=None, primary_key=True)
    weekly_review_id: int
    weekly_review_item_id: Optional[int] = None
    action_type: str = "RESEARCH"
    description: str = ""
    owner: str = "USER"
    due_date: Optional[str] = None
    status: str = "OPEN"
    verification_method: str = ""
    verification_result: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
