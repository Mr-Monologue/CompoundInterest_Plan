"""v2.1 User Confirmation — application service (stabilized)."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from sqlmodel import Session, select
from db.models import (WeeklyInvestmentPlan, WeeklyPlanItem, Transaction)
from application.models_reconciliation import (PlanItemUserDecision, ExecutionRecord, ReconciliationRecord)

VALID_ACTIONS = {"APPROVED", "SKIPPED", "DEFERRED", "CANCELLED"}
VALID_EXEC_STATUS = {"PENDING", "EXECUTED", "FAILED", "CANCELLED"}
VALID_RECONCILE_STATUS = {"PENDING", "MATCHED", "MISMATCH", "REJECTED"}
EPSILON = Decimal("0.01")


def submit_decision(session: Session, item_id: int, data: dict) -> dict:
    """User approves/skips/defers/cancels. Strict validation. No auto-trade."""
    item = session.get(WeeklyPlanItem, item_id)
    if not item:
        return {"ok": False, "error": "Item not found"}

    plan = session.get(WeeklyInvestmentPlan, item.weekly_plan_id)
    if not plan or plan.status != "FROZEN":
        return {"ok": False, "error": "Plan must be FROZEN"}

    action = data.get("user_action", "PENDING")
    if action not in VALID_ACTIONS:
        return {"ok": False, "error": f"Invalid action: {action}"}

    # Lock: if already executed or reconciled, cannot modify decision
    exec_rec = session.exec(select(ExecutionRecord).where(
        ExecutionRecord.weekly_plan_item_id == item_id)).first()
    if exec_rec and exec_rec.execution_status in ("EXECUTED",):
        rec = session.exec(select(ReconciliationRecord).where(
            ReconciliationRecord.execution_record_id == exec_rec.id)).first()
        if rec and rec.reconciliation_status == "MATCHED":
            return {"ok": False, "error": "Decision locked: already executed and reconciled"}

    if action == "APPROVED":
        if item.action in ("BLOCKED", "REVIEW_REQUIRED"):
            return {"ok": False, "error": "Cannot approve BLOCKED or REVIEW_REQUIRED item"}
        if item.data_quality_status not in ("PASS", "WARNING"):
            return {"ok": False, "error": f"Data quality {item.data_quality_status} blocks approval"}
        if item.exposure_status in ("BLOCKED", "REVIEW_REQUIRED", "GUARD_ERROR"):
            return {"ok": False, "error": f"Exposure status {item.exposure_status} blocks approval"}
        if item.risk_status in ("BLOCKED", "FAILED"):
            return {"ok": False, "error": f"Risk status {item.risk_status} blocks approval"}
        if item.final_amount is None or item.final_amount <= 0:
            return {"ok": False, "error": "No executable final_amount"}
        approved = data.get("approved_amount", item.final_amount)
        if approved is None or float(approved) <= 0:
            return {"ok": False, "error": "approved_amount must be positive"}
        if float(approved) > float(item.final_amount):
            return {"ok": False, "error": f"approved_amount {approved} > final_amount {item.final_amount}"}
    elif action == "SKIPPED":
        if not data.get("reason", "").strip():
            return {"ok": False, "error": "SKIPPED requires a reason"}
        approved = None
    else:
        approved = None

    existing = session.exec(select(PlanItemUserDecision).where(
        PlanItemUserDecision.weekly_plan_item_id == item_id)).first()
    now = datetime.now()
    if existing:
        existing.user_action = action; existing.approved_amount = approved
        existing.reason = data.get("reason", ""); existing.user_note = data.get("user_note", "")
        existing.decided_at = now; existing.updated_at = now
    else:
        existing = PlanItemUserDecision(weekly_plan_item_id=item_id, user_action=action,
                                        approved_amount=approved, reason=data.get("reason", ""),
                                        user_note=data.get("user_note", ""), decided_at=now)
        session.add(existing)
    session.commit()
    return {"ok": True, "item_id": item_id, "action": action, "approved_amount": approved}


def get_decision(session: Session, item_id: int) -> dict:
    ud = session.exec(select(PlanItemUserDecision).where(
        PlanItemUserDecision.weekly_plan_item_id == item_id)).first()
    if not ud:
        return {"ok": False, "error": "No decision"}
    return {"ok": True, "item_id": item_id, "user_action": ud.user_action,
            "approved_amount": ud.approved_amount, "reason": ud.reason, "user_note": ud.user_note,
            "decided_at": str(ud.decided_at) if ud.decided_at else None}


def submit_execution(session: Session, item_id: int, data: dict) -> dict:
    """User reports real execution. Requires prior APPROVED decision. NEVER auto-fills."""
    item = session.get(WeeklyPlanItem, item_id)
    if not item:
        return {"ok": False, "error": "Item not found"}

    decision = session.exec(select(PlanItemUserDecision).where(
        PlanItemUserDecision.weekly_plan_item_id == item_id)).first()
    if not decision or decision.user_action != "APPROVED":
        return {"ok": False, "error": "Item must be APPROVED before execution"}

    status = data.get("execution_status", "EXECUTED")
    if status not in VALID_EXEC_STATUS:
        return {"ok": False, "error": f"Invalid status: {status}"}

    if status == "EXECUTED":
        if not data.get("actual_amount") or float(data["actual_amount"]) <= 0:
            return {"ok": False, "error": "actual_amount must be > 0"}
        if not data.get("actual_price") or float(data["actual_price"]) <= 0:
            return {"ok": False, "error": "actual_price must be > 0"}
        if not data.get("actual_units") or float(data["actual_units"]) <= 0:
            return {"ok": False, "error": "actual_units must be > 0"}
        if not data.get("executed_at"):
            return {"ok": False, "error": "executed_at required"}
        if not data.get("external_reference", "").strip():
            return {"ok": False, "error": "external_reference required"}

    ext_ref = data.get("external_reference") or None

    # One execution per item
    existing = session.exec(select(ExecutionRecord).where(
        ExecutionRecord.weekly_plan_item_id == item_id)).first()
    if existing:
        if ext_ref and existing.external_reference and ext_ref != existing.external_reference:
            return {"ok": False, "error": "IDEMPOTENCY_CONFLICT: different external_reference"}
        if ext_ref and existing.external_reference == ext_ref:
            return {"ok": True, "execution_id": existing.id, "status": existing.execution_status, "idempotent": True}
        existing.execution_status = status
        existing.actual_amount = data.get("actual_amount")
        existing.actual_price = data.get("actual_price")
        existing.actual_units = data.get("actual_units")
        existing.fee = float(data.get("fee", 0) or 0)
        existing.platform = data.get("platform", "")
        existing.external_reference = ext_ref
        existing.user_note = data.get("user_note", "")
        existing.user_decision_id = decision.id
        if data.get("executed_at"):
            try:
                existing.executed_at = datetime.fromisoformat(str(data["executed_at"]))
            except:
                existing.executed_at = datetime.now()
        session.commit()
        return {"ok": True, "execution_id": existing.id, "status": existing.execution_status, "idempotent": True}

    # New record
    exec_dt = datetime.now()
    if data.get("executed_at"):
        try:
            exec_dt = datetime.fromisoformat(str(data["executed_at"]))
        except:
            pass
    er = ExecutionRecord(weekly_plan_item_id=item_id, user_decision_id=decision.id,
                         execution_status=status, actual_amount=data.get("actual_amount"),
                         actual_price=data.get("actual_price"), actual_units=data.get("actual_units"),
                         fee=float(data.get("fee", 0) or 0), platform=data.get("platform", ""),
                         external_reference=ext_ref, user_note=data.get("user_note", ""), executed_at=exec_dt)
    session.add(er)
    session.commit()
    return {"ok": True, "execution_id": er.id, "status": status, "user_decision_id": decision.id}


def get_execution(session: Session, item_id: int) -> dict:
    er = session.exec(select(ExecutionRecord).where(
        ExecutionRecord.weekly_plan_item_id == item_id)).first()
    if not er:
        return {"ok": False, "error": "No execution record"}
    return {"ok": True, "execution": {k: v for k, v in er.__dict__.items() if not k.startswith("_")}}


def reconcile_execution(session: Session, execution_id: int, data: dict) -> dict:
    er = session.get(ExecutionRecord, execution_id)
    if not er:
        return {"ok": False, "error": "Not found"}

    existing = session.exec(select(ReconciliationRecord).where(
        ReconciliationRecord.execution_record_id == execution_id)).first()
    if existing and existing.reconciliation_status == "MATCHED" and existing.transaction_id:
        return {"ok": True, "reconciliation_id": existing.id, "status": "MATCHED",
                "transaction_id": existing.transaction_id, "idempotent": True}

    item = session.get(WeeklyPlanItem, er.weekly_plan_item_id)
    decision = session.exec(select(PlanItemUserDecision).where(
        PlanItemUserDecision.weekly_plan_item_id == er.weekly_plan_item_id)).first()

    planned = Decimal(str(item.final_amount)) if item.final_amount else Decimal("0")
    approved = Decimal(str(decision.approved_amount)) if decision and decision.approved_amount else planned
    actual = Decimal(str(er.actual_amount)) if er.actual_amount else Decimal("0")

    approval_variance = approved - planned
    execution_variance = actual - approved
    plan_execution_variance = actual - planned
    matched = abs(execution_variance) <= EPSILON

    rec = ReconciliationRecord(execution_record_id=execution_id,
                               reconciliation_status="PENDING",
                               planned_amount=float(planned), approved_amount=float(approved),
                               actual_amount=float(actual),
                               amount_variance=float(plan_execution_variance),
                               evidence=str({"approval_variance": float(approval_variance),
                                             "execution_variance": float(execution_variance)}),
                               reconciled_at=datetime.now(), reconciled_by="user")

    user_confirm = data.get("confirm", False)

    # Create Transaction only if ALL conditions met
    if (decision and decision.user_action == "APPROVED"
            and er.execution_status == "EXECUTED"
            and matched and user_confirm
            and actual > 0 and er.actual_price and er.actual_price > 0
            and er.actual_units and er.actual_units > 0
            and er.external_reference):
        existing_txn = session.exec(select(Transaction).where(
            Transaction.source_execution_id == er.id)).first()
        if not existing_txn:
            with session.begin():
                txn = Transaction(asset_code=item.asset_code, type="BUY",
                                  date=er.executed_at or datetime.now(),
                                  price=er.actual_price, amount=float(actual),
                                  fee=er.fee, units=er.actual_units,
                                  source_execution_id=er.id)
                session.add(txn)
                session.flush()
                rec.reconciliation_status = "MATCHED"
                rec.transaction_id = txn.id
                session.add(rec)
            return {"ok": True, "reconciliation_id": rec.id, "status": "MATCHED",
                    "transaction_id": txn.id, "variance": float(plan_execution_variance)}
    elif matched:
        rec.reconciliation_status = "MATCHED"
        session.add(rec)
        session.commit()
    else:
        rec.reconciliation_status = "MISMATCH"
        session.add(rec)
        session.commit()

    return {"ok": True, "reconciliation_id": rec.id, "status": rec.reconciliation_status,
            "approval_variance": float(approval_variance), "execution_variance": float(execution_variance),
            "variance": float(plan_execution_variance), "transaction_id": getattr(rec, 'transaction_id', None)}


def get_execution_summary(session: Session, plan_id: int) -> dict:
    items = session.exec(select(WeeklyPlanItem).where(WeeklyPlanItem.weekly_plan_id == plan_id)).all()
    summary = []
    for item in items:
        d = session.exec(select(PlanItemUserDecision).where(
            PlanItemUserDecision.weekly_plan_item_id == item.id)).first()
        e = session.exec(select(ExecutionRecord).where(
            ExecutionRecord.weekly_plan_item_id == item.id)).first()
        r = session.exec(select(ReconciliationRecord).where(
            ReconciliationRecord.execution_record_id == e.id)).first() if e else None
        summary.append({"asset_code": item.asset_code, "action": item.action,
                        "planned": item.final_amount, "approved": d.approved_amount if d else None,
                        "actual": e.actual_amount if e else None, "variance": r.amount_variance if r else None,
                        "reconciled": r.reconciliation_status if r else "PENDING"})
    return {"ok": True, "plan_id": plan_id, "items": summary}
