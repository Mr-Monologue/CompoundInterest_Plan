"""v2.1 User Confirmation — final ledger gate (stabilized)."""
from decimal import Decimal
from datetime import datetime
from sqlmodel import Session, select
from db.models import WeeklyInvestmentPlan, WeeklyPlanItem, Transaction
from application.models_reconciliation import PlanItemUserDecision, ExecutionRecord, ReconciliationRecord

VALID_ACTIONS = {"APPROVED", "SKIPPED", "DEFERRED", "CANCELLED"}
EPSILON = Decimal("0.01")


def _is_locked(session, item_id):
    """Check if decision is locked by execution/reconciliation/transaction."""
    er = session.exec(select(ExecutionRecord).where(
        ExecutionRecord.weekly_plan_item_id == item_id)).first()
    if er and er.execution_status in ("EXECUTED",):
        return "DECISION_LOCKED_AFTER_EXECUTION"
    if er:
        rec = session.exec(select(ReconciliationRecord).where(
            ReconciliationRecord.execution_record_id == er.id)).first()
        if rec:
            return "DECISION_LOCKED_AFTER_EXECUTION"
        txn = session.exec(select(Transaction).where(
            Transaction.source_execution_id == er.id)).first()
        if txn:
            return "DECISION_LOCKED_AFTER_EXECUTION"
    return None


def submit_decision(session: Session, item_id: int, data: dict) -> dict:
    item = session.get(WeeklyPlanItem, item_id)
    if not item:
        return {"ok": False, "error": "Item not found"}

    plan = session.get(WeeklyInvestmentPlan, item.weekly_plan_id)
    if not plan or plan.status != "FROZEN":
        return {"ok": False, "error": "Plan must be FROZEN"}

    action = data.get("user_action", "PENDING") if isinstance(data, dict) else data.user_action
    if action not in VALID_ACTIONS:
        return {"ok": False, "error": f"Invalid action: {action}"}

    locked = _is_locked(session, item_id)
    if locked:
        return {"ok": False, "error": locked}

    if action == "APPROVED":
        if item.action in ("BLOCKED", "REVIEW_REQUIRED"):
            return {"ok": False, "error": "Cannot approve BLOCKED or REVIEW_REQUIRED"}
        if item.data_quality_status not in ("PASS", "WARNING"):
            return {"ok": False, "error": f"Data quality {item.data_quality_status} blocks approval"}
        if item.exposure_status in ("BLOCKED", "REVIEW_REQUIRED", "GUARD_ERROR"):
            return {"ok": False, "error": f"Exposure {item.exposure_status} blocks approval"}
        if item.risk_status in ("BLOCKED", "FAILED"):
            return {"ok": False, "error": f"Risk {item.risk_status} blocks approval"}
        if item.final_amount is None or item.final_amount <= 0:
            return {"ok": False, "error": "No executable final_amount"}
        approved = data.get("approved_amount", item.final_amount)
        if approved is None or float(approved) <= 0:
            return {"ok": False, "error": "approved_amount must be > 0"}
        if float(approved) > float(item.final_amount):
            return {"ok": False, "error": f"{approved} > final {item.final_amount}"}
    elif action == "SKIPPED":
        reason = data.get("reason", "")
        if not reason.strip():
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


def submit_execution(session: Session, item_id: int, data: dict) -> dict:
    item = session.get(WeeklyPlanItem, item_id)
    if not item:
        return {"ok": False, "error": "Item not found"}

    decision = session.exec(select(PlanItemUserDecision).where(
        PlanItemUserDecision.weekly_plan_item_id == item_id)).first()
    if not decision or decision.user_action != "APPROVED":
        return {"ok": False, "error": "Item must be APPROVED before execution"}

    status = data.get("execution_status", "EXECUTED")

    if status == "EXECUTED":
        for field in ["actual_amount", "actual_price", "actual_units"]:
            v = data.get(field)
            if v is None or float(v) <= 0:
                return {"ok": False, "error": f"{field} must be > 0"}
        if not data.get("platform", "").strip():
            return {"ok": False, "error": "platform required"}
        ext_ref = data.get("external_reference", "").strip()
        if not ext_ref:
            return {"ok": False, "error": "external_reference required"}
        exec_str = data.get("executed_at", "")
        try:
            exec_dt = datetime.fromisoformat(str(exec_str))
        except Exception:
            return {"ok": False, "error": "INVALID_EXECUTED_AT"}
    else:
        exec_dt = None
        ext_ref = data.get("external_reference") or None

    # Check existing execution record
    existing = session.exec(select(ExecutionRecord).where(
        ExecutionRecord.weekly_plan_item_id == item_id)).first()
    if existing:
        if existing.execution_status == "EXECUTED":
            rec = session.exec(select(ReconciliationRecord).where(
                ReconciliationRecord.execution_record_id == existing.id)).first()
            if rec and rec.reconciliation_status == "MATCHED":
                return {"ok": True, "execution_id": existing.id, "status": existing.execution_status,
                        "idempotent": True, "note": "already executed and matched"}
        # Same external_ref, same payload → idempotent
        if ext_ref and existing.external_reference == ext_ref:
            same = (existing.actual_amount == data.get("actual_amount") and
                    existing.actual_price == data.get("actual_price") and
                    existing.actual_units == data.get("actual_units"))
            if same:
                return {"ok": True, "execution_id": existing.id, "status": existing.execution_status, "idempotent": True}
            return {"ok": False, "error": "IDEMPOTENCY_CONFLICT"}
        # Different payload → update
        existing.execution_status = status
        existing.actual_amount = data.get("actual_amount"); existing.actual_price = data.get("actual_price")
        existing.actual_units = data.get("actual_units"); existing.fee = float(data.get("fee", 0) or 0)
        existing.platform = data.get("platform", ""); existing.external_reference = ext_ref
        existing.user_note = data.get("user_note", ""); existing.user_decision_id = decision.id
        if exec_dt:
            existing.executed_at = exec_dt
        session.commit()
        return {"ok": True, "execution_id": existing.id, "status": status, "user_decision_id": decision.id}

    er = ExecutionRecord(weekly_plan_item_id=item_id, user_decision_id=decision.id,
                         execution_status=status, actual_amount=data.get("actual_amount"),
                         actual_price=data.get("actual_price"), actual_units=data.get("actual_units"),
                         fee=float(data.get("fee", 0) or 0), platform=data.get("platform", ""),
                         external_reference=ext_ref, user_note=data.get("user_note", ""),
                         executed_at=exec_dt)
    session.add(er)
    session.commit()
    return {"ok": True, "execution_id": er.id, "status": status, "user_decision_id": decision.id}


def reconcile_execution(session: Session, execution_id: int, data: dict) -> dict:
    er = session.get(ExecutionRecord, execution_id)
    if not er:
        return {"ok": False, "error": "Not found"}

    existing = session.exec(select(ReconciliationRecord).where(
        ReconciliationRecord.execution_record_id == execution_id)).first()

    # Already matched + has transaction → idempotent
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

    rec = existing or ReconciliationRecord(execution_record_id=execution_id)
    rec.planned_amount = float(planned); rec.approved_amount = float(approved)
    rec.actual_amount = float(actual); rec.amount_variance = float(plan_execution_variance)
    rec.evidence = str({"approval_variance": float(approval_variance), "execution_variance": float(execution_variance)})
    rec.reconciled_at = datetime.now(); rec.reconciled_by = "user"

    user_confirm = data.get("confirm", False) if isinstance(data, dict) else data.confirm

    if (decision and decision.user_action == "APPROVED"
            and er.execution_status == "EXECUTED"
            and matched and user_confirm
            and actual > 0 and er.actual_price and er.actual_price > 0
            and er.actual_units and er.actual_units > 0
            and er.external_reference):
        existing_txn = session.exec(select(Transaction).where(
            Transaction.source_execution_id == er.id)).first()
        if not existing_txn:
            try:
                txn = Transaction(asset_code=item.asset_code, type="BUY",
                                  date=er.executed_at or datetime.now(),
                                  price=er.actual_price, amount=float(actual),
                                  fee=er.fee, units=er.actual_units,
                                  source_execution_id=er.id)
                session.add(txn)
                session.flush()
                rec.reconciliation_status = "MATCHED"
                rec.transaction_id = txn.id
                if existing:
                    session.merge(rec)
                else:
                    session.add(rec)
                session.commit()
                return {"ok": True, "reconciliation_id": rec.id, "status": "MATCHED",
                        "transaction_id": txn.id, "variance": float(plan_execution_variance)}
            except Exception:
                session.rollback()
                return {"ok": False, "error": "TRANSACTION_CREATION_FAILED"}

    rec.reconciliation_status = "MATCHED" if matched else "MISMATCH"
    if existing:
        session.merge(rec)
    else:
        session.add(rec)
    session.commit()
    return {"ok": True, "reconciliation_id": rec.id, "status": rec.reconciliation_status,
            "variance": float(plan_execution_variance), "transaction_id": getattr(rec, 'transaction_id', None)}
