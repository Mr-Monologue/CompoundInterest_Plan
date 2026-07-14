"""v2.1 Weekly Review API — Pydantic models."""
from typing import Optional, Dict, Literal
from pydantic import BaseModel


class GenerateReviewRequest(BaseModel):
    weekly_plan_id: int
    rebuild: bool = False


class UserReviewRequest(BaseModel):
    overall_note: str = ""
    item_variance_reasons: Dict[str, str] = {}
    confirm: bool = False


class CloseReviewRequest(BaseModel):
    confirm_close: Literal[True]


class FollowUpActionUpdateRequest(BaseModel):
    status: Literal["DONE", "DISMISSED"]
    verification_result: str = ""
