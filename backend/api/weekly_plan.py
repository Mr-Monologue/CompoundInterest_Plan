"""v2.1 Weekly Plan API router."""
from fastapi import APIRouter, Depends
from sqlmodel import Session
from db.database import get_session
from application.weekly_plan import (create_draft_weekly_plan, add_existing_decisions_to_plan,
                                      freeze_weekly_plan, get_weekly_plan, list_weekly_plans,
                                      build_weekly_investment_plan)

router = APIRouter(prefix="/api/weekly-plans", tags=["weekly-plans"])


@router.post("")
def create_plan(data: dict, session: Session = Depends(get_session)):
    return create_draft_weekly_plan(session, data.get("week_start", ""), data.get("config_id", 1))


@router.get("")
def list_plans(session: Session = Depends(get_session)):
    return list_weekly_plans(session)


@router.get("/{plan_id}")
def get_plan(plan_id: int, session: Session = Depends(get_session)):
    return get_weekly_plan(session, plan_id)


@router.post("/{plan_id}/freeze")
def freeze_plan(plan_id: int, session: Session = Depends(get_session)):
    return freeze_weekly_plan(session, plan_id)


@router.post("/{plan_id}/add-decisions")
def add_decisions(plan_id: int, data: dict, session: Session = Depends(get_session)):
    return add_existing_decisions_to_plan(session, plan_id, data.get("date", ""))


@router.post("/build")
def build_plan(data: dict, session: Session = Depends(get_session)):
    return build_weekly_investment_plan(session, data.get("week_start", ""),
                                        data.get("config_id", 1), data.get("rebuild", False))
