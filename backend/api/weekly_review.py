"""v2.1 Weekly Review API — strict Pydantic models + router."""
from typing import Dict, Literal
from pydantic import BaseModel, PositiveInt, Field
from fastapi import APIRouter, Depends
from sqlmodel import Session
from db.database import get_session
from application.weekly_review import (generate_weekly_review, get_review, get_plan_review,
                                        submit_user_review, close_weekly_review,
                                        get_pending_reviews, update_follow_up)


class GenerateReviewRequest(BaseModel):
    weekly_plan_id: PositiveInt
    rebuild: bool = False


class UserReviewRequest(BaseModel):
    overall_note: str = ""
    item_variance_reasons: Dict[int, str] = Field(default_factory=dict)
    confirm: bool = False

    @property
    def has_all_reasons(self) -> bool:
        return all(v.strip() for v in self.item_variance_reasons.values() if v is not None)


class CloseReviewRequest(BaseModel):
    confirm_close: Literal[True]


class FollowUpActionUpdateRequest(BaseModel):
    status: Literal["DONE", "DISMISSED"]
    verification_result: str = ""


router = APIRouter(prefix="/api", tags=["weekly-review"])


@router.post("/weekly-reviews/generate")
def api_generate(data: GenerateReviewRequest, session: Session = Depends(get_session)):
    return generate_weekly_review(session, data.weekly_plan_id, data.rebuild)


@router.get("/weekly-reviews/{review_id}")
def api_get_review(review_id: int, session: Session = Depends(get_session)):
    return get_review(session, review_id)


@router.get("/weekly-plans/{plan_id}/review")
def api_plan_review(plan_id: int, session: Session = Depends(get_session)):
    return get_plan_review(session, plan_id)


@router.post("/weekly-reviews/{review_id}/user-review")
def api_user_review(review_id: int, data: UserReviewRequest, session: Session = Depends(get_session)):
    return submit_user_review(session, review_id, data.model_dump())


@router.post("/weekly-reviews/{review_id}/close")
def api_close(review_id: int, data: CloseReviewRequest, session: Session = Depends(get_session)):
    return close_weekly_review(session, review_id, {"confirm_close": True})


@router.get("/weekly-reviews/pending")
def api_pending(session: Session = Depends(get_session)):
    return get_pending_reviews(session)


@router.get("/follow-up-actions")
def api_actions(session: Session = Depends(get_session)):
    from sqlmodel import select
    from application.models_review import FollowUpAction
    actions = session.exec(select(FollowUpAction).order_by(FollowUpAction.created_at.desc()).limit(50)).all()
    return {"ok": True, "actions": [{k: v for k, v in a.__dict__.items() if not k.startswith("_")} for a in actions]}


@router.patch("/follow-up-actions/{action_id}")
def api_update_action(action_id: int, data: FollowUpActionUpdateRequest, session: Session = Depends(get_session)):
    if data.status == "DONE" and not data.verification_result.strip():
        return {"ok": False, "error": "INVALID_FOLLOW_UP_TRANSITION", "detail": "verification_result required for DONE"}
    return update_follow_up(session, action_id, {"status": data.status, "verification_result": data.verification_result})
