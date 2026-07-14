"""v2.1 Weekly Review API router."""
from fastapi import APIRouter, Depends
from sqlmodel import Session
from db.database import get_session
from application.weekly_review import (generate_weekly_review, get_review, get_plan_review,
                                        submit_user_review, close_weekly_review,
                                        get_pending_reviews, update_follow_up)

router = APIRouter(prefix="/api", tags=["weekly-review"])


@router.post("/weekly-reviews/generate")
def api_generate(data: dict, session: Session = Depends(get_session)):
    return generate_weekly_review(session, data.get("weekly_plan_id", 0), data.get("rebuild", False))


@router.get("/weekly-reviews/{review_id}")
def api_get_review(review_id: int, session: Session = Depends(get_session)):
    return get_review(session, review_id)


@router.get("/weekly-plans/{plan_id}/review")
def api_plan_review(plan_id: int, session: Session = Depends(get_session)):
    return get_plan_review(session, plan_id)


@router.post("/weekly-reviews/{review_id}/user-review")
def api_user_review(review_id: int, data: dict, session: Session = Depends(get_session)):
    return submit_user_review(session, review_id, data)


@router.post("/weekly-reviews/{review_id}/close")
def api_close(review_id: int, data: dict, session: Session = Depends(get_session)):
    return close_weekly_review(session, review_id, data)


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
def api_update_action(action_id: int, data: dict, session: Session = Depends(get_session)):
    return update_follow_up(session, action_id, data)
