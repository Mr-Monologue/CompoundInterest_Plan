"""v2.1 User Confirmation API — Pydantic models + router."""
from decimal import Decimal
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlmodel import Session
from db.database import get_session
from application.user_confirmation import (submit_decision, get_decision,
                                           submit_execution, get_execution,
                                           reconcile_execution, get_execution_summary)


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


router = APIRouter(prefix="/api", tags=["user-confirmation"])


@router.post("/weekly-plan-items/{item_id}/decision")
def api_decision(item_id: int, data: DecisionRequest, session: Session = Depends(get_session)):
    return submit_decision(session, item_id, data.model_dump())


@router.get("/weekly-plan-items/{item_id}/decision")
def api_get_decision(item_id: int, session: Session = Depends(get_session)):
    return get_decision(session, item_id)


@router.post("/weekly-plan-items/{item_id}/execution")
def api_execution(item_id: int, data: ExecutionRequest, session: Session = Depends(get_session)):
    return submit_execution(session, item_id, data.model_dump())


@router.get("/weekly-plan-items/{item_id}/execution")
def api_get_execution(item_id: int, session: Session = Depends(get_session)):
    return get_execution(session, item_id)


@router.post("/executions/{exec_id}/reconcile")
def api_reconcile(exec_id: int, data: ReconciliationRequest, session: Session = Depends(get_session)):
    return reconcile_execution(session, exec_id, {"confirm": data.confirm})


@router.get("/weekly-plans/{plan_id}/execution-summary")
def api_summary(plan_id: int, session: Session = Depends(get_session)):
    return get_execution_summary(session, plan_id)
