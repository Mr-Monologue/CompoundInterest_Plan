"""v2.1 User Confirmation + Execution Reconciliation — application service."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from sqlmodel import Session, select
from db.models import (WeeklyInvestmentPlan, WeeklyPlanItem, Transaction)
from application.models_reconciliation import (PlanItemUserDecision, ExecutionRecord, ReconciliationRecord)


def submit_decision(session: Session, item_id: int, data: dict) -> dict:
    """User approves/skips/defers/cancels a plan item. No auto-trade, no pool deduction."""
    item = session.get(WeeklyPlanItem, item_id)
    if not item:
        return {"ok": False, "error": "Item not found"}

    plan = session.get(WeeklyInvestmentPlan, item.weekly_plan_id)
    if not plan or plan.status not in ("FROZEN",):
        return {"ok": False, "error": "Plan must be FROZEN for user decisions"}

    action = data.get("user_action", "PENDING")

    if action == "APPROVED":
        if item.action in ("BLOCKED", "REVIEW_REQUIRED") or item.data_quality_status in ("BLOCKED", "SOURCE_ERROR"):
            return {"ok": False, "error": "Cannot approve BLOCKED or REVIEW_REQUIRED item"}
        approved = data.get("approved_amount", item.final_amount)
        if approved is not None and item.final_amount is not None and float(approved) > float(item.final_amount):
            return {"ok": False, "error": f"Approved amount {approved} exceeds final amount {item.final_amount}"}
    else:
        approved = None

    # Idempotent: one decision per item
    existing = session.exec(select(PlanItemUserDecision).where(
        PlanItemUserDecision.weekly_plan_item_id == item_id)).first()
    if existing:
        existing.user_action = action
        existing.approved_amount = approved
        existing.reason = data.get("reason", "")
        existing.user_note = data.get("user_note", "")
        existing.decided_at = datetime.now()
        existing.updated_at = datetime.now()
    else:
        existing = PlanItemUserDecision(weekly_plan_item_id=item_id, user_action=action,
                                        approved_amount=approved, reason=data.get("reason", ""),
                                        user_note=data.get("user_note", ""), decided_at=datetime.now())
        session.add(existing)
    session.commit()

    # Safety: never auto-create Transaction, never deduct pool
    return {"ok": True, "item_id": item_id, "action": action, "approved_amount": approved,
            "no_transaction_created": True, "no_pool_deduction": True}


def get_decision(session: Session, item_id: int) -> dict:
    """Get current user decision for a plan item."""
    ud = session.exec(select(PlanItemUserDecision).where(
        PlanItemUserDecision.weekly_plan_item_id == item_id)).first()
    if not ud:
        return {"ok": False, "error": "No decision yet"}
    return {"ok": True, "item_id": item_id, "user_action": ud.user_action,
            "approved_amount": ud.approved_amount, "reason": ud.reason, "user_note": ud.user_note,
            "decided_at": str(ud.decided_at) if ud.decided_at else None}


def submit_execution(session: Session, item_id: int, data: dict) -> dict:
    """User reports real execution facts. Agent NEVER fills price/units/amount automatically."""
    item = session.get(WeeklyPlanItem, item_id)
    if not item:
        return {"ok": False, "error": "Item not found"}

    # Require actual facts
    actual_amount = data.get("actual_amount")
    if actual_amount is None and data.get("execution_status") == "EXECUTED":
        return {"ok": False, "error": "Cannot mark EXECUTED without actual_amount"}

    # Duplicate external_reference check
    ext_ref = data.get("external_reference", "")
    if ext_ref:
        existing = session.exec(select(ExecutionRecord).where(
            ExecutionRecord.external_reference == ext_ref)).first()
        if existing:
            return {"ok": False, "error": f"Duplicate external_reference: {ext_ref}"}

    # Idempotent
    existing = session.exec(select(ExecutionRecord).where(
        ExecutionRecord.weekly_plan_item_id == item_id)).first()
    if existing:
        existing.execution_status = data.get("execution_status", "EXECUTED")
        existing.actual_amount = actual_amount
        existing.actual_price = data.get("actual_price")
        existing.actual_units = data.get("actual_units")
        existing.fee = float(data.get("fee", 0) or 0)
        existing.platform = data.get("platform", "")
        existing.external_reference = ext_ref
        existing.user_note = data.get("user_note", "")
        if data.get("executed_at"):
            existing.executed_at = datetime.now()
    else:
        existing = ExecutionRecord(weekly_plan_item_id=item_id, execution_status=data.get("execution_status", "EXECUTED"),
                                   actual_amount=actual_amount, actual_price=data.get("actual_price"),
                                   actual_units=data.get("actual_units"), fee=float(data.get("fee", 0) or 0),
                                   platform=data.get("platform", ""), external_reference=ext_ref,
                                   user_note=data.get("user_note", ""), executed_at=datetime.now())
        session.add(existing)
    session.commit()
    return {"ok": True, "execution_id": existing.id, "status": existing.execution_status}


def get_execution(session: Session, item_id: int) -> dict:
    er = session.exec(select(ExecutionRecord).where(
        ExecutionRecord.weekly_plan_item_id == item_id)).first()
    if not er:
        return {"ok": False, "error": "No execution record"}
    return {"ok": True, "execution": {k: v for k, v in er.__dict__.items() if not k.startswith("_")}}


def reconcile_execution(session: Session, execution_id: int, data: dict) -> dict:
    """Compare plan → approved → actual, calculate variance, optionally create Transaction."""
    er = session.get(ExecutionRecord, execution_id)
    if not er:
        return {"ok": False, "error": "Execution record not found"}

    # Idempotent
    existing = session.exec(select(ReconciliationRecord).where(
        ReconciliationRecord.execution_record_id == execution_id)).first()
    if existing:
        return {"ok": True, "reconciliation_id": existing.id, "status": existing.reconciliation_status,
                "idempotent": True}

    item = session.get(WeeklyPlanItem, er.weekly_plan_item_id)
    decision = session.exec(select(PlanItemUserDecision).where(
        PlanItemUserDecision.weekly_plan_item_id == er.weekly_plan_item_id)).first()

    planned = item.final_amount
    approved = decision.approved_amount if decision else None
    actual = er.actual_amount

    variance = None
    if planned is not None and actual is not None:
        variance = round(float(Decimal(str(actual)) - Decimal(str(planned))), 2)

    rec = ReconciliationRecord(execution_record_id=execution_id, reconciliation_status="PENDING",
                               planned_amount=planned, approved_amount=approved, actual_amount=actual,
                               amount_variance=variance, evidence=str({"source": "user_reported"}),
                               reconciled_at=datetime.now(), reconciled_by="user")

    # Only create Transaction if user explicitly confirms MATCHED
    user_confirm = data.get("confirm", False)
    if user_confirm and variance is not None and abs(variance) < 0.02 and actual > 0:
        txn = Transaction(asset_code=item.asset_code, type="buy", price=er.actual_price or 0,
                          amount=actual, fee=er.fee, units=er.actual_units or 0,
                          source_execution_id=er.id)
        session.add(txn)
        rec.reconciliation_status = "MATCHED"
        rec.transaction_id = txn.id

    session.add(rec)
    session.commit()
    return {"ok": True, "reconciliation_id": rec.id, "status": rec.reconciliation_status,
            "planned": planned, "approved": approved, "actual": actual, "variance": variance}


def get_execution_summary(session: Session, plan_id: int) -> dict:
    items = session.exec(select(WeeklyPlanItem).where(WeeklyPlanItem.weekly_plan_id == plan_id)).all()
    summary = []
    for item in items:
        decision = session.exec(select(PlanItemUserDecision).where(
            PlanItemUserDecision.weekly_plan_item_id == item.id)).first()
        execution = session.exec(select(ExecutionRecord).where(
            ExecutionRecord.weekly_plan_item_id == item.id)).first()
        rec = session.exec(select(ReconciliationRecord).where(
            ReconciliationRecord.execution_record_id == execution.id)).first() if execution else None
        summary.append({
            "asset_code": item.asset_code, "action": item.action,
            "planned_amount": item.final_amount,
            "approved_amount": decision.approved_amount if decision else None,
            "actual_amount": execution.actual_amount if execution else None,
            "variance": rec.amount_variance if rec else None,
            "reconciled": rec.reconciliation_status if rec else "PENDING",
        })
    return {"ok": True, "plan_id": plan_id, "items": summary}
