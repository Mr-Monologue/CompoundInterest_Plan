"""v2.1 User Confirmation API router."""
from fastapi import APIRouter, Depends
from sqlmodel import Session
from db.database import get_session
from application.user_confirmation import (submit_decision, get_decision, submit_execution,
                                            get_execution, reconcile_execution, get_execution_summary)

router = APIRouter(prefix="/api", tags=["user-confirmation"])


@router.post("/weekly-plan-items/{item_id}/decision")
def api_submit_decision(item_id: int, data: dict, session: Session = Depends(get_session)):
    return submit_decision(session, item_id, data)


@router.get("/weekly-plan-items/{item_id}/decision")
def api_get_decision(item_id: int, session: Session = Depends(get_session)):
    return get_decision(session, item_id)


@router.post("/weekly-plan-items/{item_id}/execution")
def api_submit_execution(item_id: int, data: dict, session: Session = Depends(get_session)):
    return submit_execution(session, item_id, data)


@router.get("/weekly-plan-items/{item_id}/execution")
def api_get_execution(item_id: int, session: Session = Depends(get_session)):
    return get_execution(session, item_id)


@router.post("/executions/{execution_id}/reconcile")
def api_reconcile(execution_id: int, data: dict, session: Session = Depends(get_session)):
    return reconcile_execution(session, execution_id, data)


@router.get("/weekly-plans/{plan_id}/execution-summary")
def api_execution_summary(plan_id: int, session: Session = Depends(get_session)):
    return get_execution_summary(session, plan_id)
