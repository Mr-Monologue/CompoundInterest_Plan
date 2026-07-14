"""v2.1 Weekly Review Generator — factual, no LLM, no scoring."""
from decimal import Decimal
from datetime import datetime
from sqlmodel import Session, select
from db.models import (WeeklyInvestmentPlan, WeeklyPlanItem, Transaction)
from application.models_reconciliation import (PlanItemUserDecision, ExecutionRecord, ReconciliationRecord)
from application.models_review import WeeklyReview, WeeklyReviewItem, FollowUpAction


def _dec(val):
    return Decimal(str(val)) if val is not None else None


def generate_weekly_review(session: Session, weekly_plan_id: int, rebuild: bool = False) -> dict:
    plan = session.get(WeeklyInvestmentPlan, weekly_plan_id)
    if not plan:
        return {"ok": False, "error": "Plan not found"}

    existing = session.exec(select(WeeklyReview).where(
        WeeklyReview.weekly_plan_id == weekly_plan_id)).first()
    if existing and not rebuild:
        items = session.exec(select(WeeklyReviewItem).where(
            WeeklyReviewItem.weekly_review_id == existing.id)).all()
        return {"ok": True, "review_id": existing.id, "status": existing.status, "idempotent": True,
                "items": [{k: v for k, v in i.__dict__.items() if not k.startswith("_")} for i in items]}

    if existing and existing.status == "CLOSED":
        return {"ok": False, "error": "Closed review cannot be rebuilt"}

    rev = existing or WeeklyReview(weekly_plan_id=weekly_plan_id, period_start=plan.week_start,
                                   period_end=plan.week_end, strategy_version=plan.strategy_version, status="DRAFT")
    rev.generated_at = datetime.now()
    rev.item_count = 0

    plan_items = session.exec(select(WeeklyPlanItem).where(
        WeeklyPlanItem.weekly_plan_id == weekly_plan_id)).all()

    if existing and rebuild:
        for old in session.exec(select(WeeklyReviewItem).where(
            WeeklyReviewItem.weekly_review_id == existing.id)).all():
            session.delete(old)
        session.flush()

    if not existing:
        session.add(rev)
        session.flush()

    count = {"approved": 0, "executed": 0, "matched": 0, "mismatch": 0, "skipped": 0,
             "deferred": 0, "cancelled": 0, "blocked": 0, "undecided": 0}

    total_planned = Decimal("0"); total_approved = Decimal("0"); total_actual = Decimal("0")
    total_matched = Decimal("0"); total_unexecuted = Decimal("0")
    total_app_var = Decimal("0"); total_exec_var = Decimal("0"); total_plan_exec_var = Decimal("0")

    for pi in plan_items:
        decision = session.exec(select(PlanItemUserDecision).where(
            PlanItemUserDecision.weekly_plan_item_id == pi.id)).first()
        execution = session.exec(select(ExecutionRecord).where(
            ExecutionRecord.weekly_plan_item_id == pi.id)).first()
        reconciliation = session.exec(select(ReconciliationRecord).where(
            ReconciliationRecord.execution_record_id == execution.id)).first() if execution else None

        planned = _dec(pi.final_amount)
        approved = _dec(decision.approved_amount) if decision else None
        actual = _dec(execution.actual_amount) if execution else None

        app_var = (approved - planned) if approved and planned else None
        exec_var = (actual - approved) if actual and approved else None
        plan_exec_var = (actual - planned) if actual and planned else None

        # Determine category
        is_blocked = (pi.action in ("BLOCKED", "REVIEW_REQUIRED") or
                      pi.data_quality_status not in ("PASS", "WARNING", "unknown") or
                      pi.exposure_status in ("BLOCKED", "REVIEW_REQUIRED", "GUARD_ERROR"))

        if is_blocked:
            category = "BLOCKED"; count["blocked"] += 1
        elif decision and decision.user_action == "APPROVED":
            if execution and execution.execution_status == "EXECUTED":
                if reconciliation and reconciliation.reconciliation_status == "MATCHED":
                    txn_chk = session.exec(select(Transaction).where(
                        Transaction.source_execution_id == execution.id)).first()
                    if txn_chk:
                        category = "EXECUTED_MATCHED"; count["matched"] += 1
                    else:
                        category = "DATA_ERROR"; count["mismatch"] += 1
                elif reconciliation and reconciliation.reconciliation_status in ("MISMATCH", "REJECTED"):
                    category = "EXECUTED_MISMATCH"; count["mismatch"] += 1
                else:
                    category = "EXECUTED_MISMATCH"; count["mismatch"] += 1
            else:
                category = "APPROVED_NOT_EXECUTED"
        elif decision and decision.user_action in ("SKIPPED", "DEFERRED", "CANCELLED"):
            category = decision.user_action
            count[decision.user_action.lower()] += 1
        elif pi.final_amount and pi.final_amount > 0:
            category = "UNDECIDED"; count["undecided"] += 1
        else:
            category = "UNDECIDED"
            if pi.action in ("BLOCKED", "REVIEW_REQUIRED"):
                category = "BLOCKED"; count["blocked"] += 1

        if planned:
            total_planned += planned
            if approved and decision.user_action == "APPROVED":
                total_approved += approved
                count["approved"] += 1
            if actual:
                total_actual += actual
                count["executed"] += 1
                if reconciliation and reconciliation.reconciliation_status == "MATCHED":
                    total_matched += actual
            if category == "APPROVED_NOT_EXECUTED":
                total_unexecuted += approved or planned

        if app_var: total_app_var += app_var
        if exec_var: total_exec_var += exec_var
        if plan_exec_var: total_plan_exec_var += plan_exec_var

        ri = WeeklyReviewItem(weekly_review_id=rev.id, weekly_plan_item_id=pi.id,
                              asset_code=pi.asset_code, asset_role=pi.asset_role,
                              plan_action=pi.action, planned_amount=float(planned) if planned else None,
                              user_action=decision.user_action if decision else "",
                              approved_amount=float(approved) if approved else None,
                              decision_reason=decision.reason if decision else "",
                              decision_note=decision.user_note if decision else "",
                              execution_status=execution.execution_status if execution else "",
                              actual_amount=float(actual) if actual else None,
                              actual_price=execution.actual_price if execution else None,
                              actual_units=execution.actual_units if execution else None,
                              reconciliation_status=reconciliation.reconciliation_status if reconciliation else "",
                              approval_variance=float(app_var) if app_var else None,
                              execution_variance=float(exec_var) if exec_var else None,
                              plan_execution_variance=float(plan_exec_var) if plan_exec_var else None,
                              review_category=category)
        session.add(ri)
        rev.item_count = count["approved"] + count["executed"] + count["matched"] + count["mismatch"] + count["skipped"] + count["deferred"] + count["cancelled"] + count["blocked"] + count["undecided"]

    rev.planned_total = float(total_planned); rev.approved_total = float(total_approved)
    rev.actual_total = float(total_actual); rev.matched_total = float(total_matched)
    rev.unexecuted_total = float(total_unexecuted)
    rev.approval_variance_total = float(total_app_var) if total_app_var else None
    rev.execution_variance_total = float(total_exec_var) if total_exec_var else None
    rev.plan_execution_variance_total = float(total_plan_exec_var) if total_plan_exec_var else None
    rev.approved_count = count["approved"]; rev.executed_count = count["executed"]
    rev.matched_count = count["matched"]; rev.mismatch_count = count["mismatch"]
    rev.skipped_count = count["skipped"]; rev.deferred_count = count["deferred"]
    rev.cancelled_count = count["cancelled"]; rev.blocked_count = count["blocked"]
    rev.undecided_count = count["undecided"]
    rev.status = "READY_FOR_USER" if (count["undecided"] == 0 and count["mismatch"] <= 0) else "INCOMPLETE"

    # Deterministic FollowUpActions
    if existing and rebuild:
        for old_fa in session.exec(select(FollowUpAction).where(
            FollowUpAction.weekly_review_id == existing.id, FollowUpAction.status.in_(("DONE",)))).all():
            pass  # keep completed actions
    else:
        if count["blocked"] > 0:
            session.add(FollowUpAction(weekly_review_id=rev.id, action_type="DATA_REPAIR",
                                       description=f"{count['blocked']} blocked items need data fix", owner="SYSTEM"))
        if count["undecided"] > 0 or (count["approved"] > 0 and count["executed"] == 0):
            session.add(FollowUpAction(weekly_review_id=rev.id, action_type="EXECUTION_MISSING",
                                       description="Approved items not yet executed", owner="USER"))
        if count["mismatch"] > 0:
            session.add(FollowUpAction(weekly_review_id=rev.id, action_type="RECONCILIATION_REQUIRED",
                                       description=f"{count['mismatch']} items need reconciliation", owner="USER"))
        for ri in session.exec(select(WeeklyReviewItem).where(
            WeeklyReviewItem.weekly_review_id == rev.id, WeeklyReviewItem.review_category == "DEFERRED")).all():
            session.add(FollowUpAction(weekly_review_id=rev.id, weekly_review_item_id=ri.id,
                                       action_type="NEXT_WEEK_CHECK", description=f"{ri.asset_code} deferred",
                                       owner="SYSTEM"))
        for ri in session.exec(select(WeeklyReviewItem).where(
            WeeklyReviewItem.weekly_review_id == rev.id, WeeklyReviewItem.review_category == "SKIPPED",
            WeeklyReviewItem.decision_reason == "")).all():
            session.add(FollowUpAction(weekly_review_id=rev.id, weekly_review_item_id=ri.id,
                                       action_type="USER_CLARIFICATION", description=f"{ri.asset_code} skipped without reason",
                                       owner="USER"))

    session.commit()
    items = session.exec(select(WeeklyReviewItem).where(
        WeeklyReviewItem.weekly_review_id == rev.id)).all()
    fas = session.exec(select(FollowUpAction).where(
        FollowUpAction.weekly_review_id == rev.id)).all()
    return {"ok": True, "review_id": rev.id, "status": rev.status,
            "review": {k: v for k, v in rev.__dict__.items() if not k.startswith("_")},
            "items": [{k: v for k, v in i.__dict__.items() if not k.startswith("_")} for i in items],
            "follow_up_actions": [{k: v for k, v in fa.__dict__.items() if not k.startswith("_")} for fa in fas]}


def get_review(session: Session, review_id: int) -> dict:
    rev = session.get(WeeklyReview, review_id)
    if not rev:
        return {"ok": False, "error": "Not found"}
    items = session.exec(select(WeeklyReviewItem).where(
        WeeklyReviewItem.weekly_review_id == review_id)).all()
    fas = session.exec(select(FollowUpAction).where(
        FollowUpAction.weekly_review_id == review_id)).all()
    return {"ok": True, "review": {k: v for k, v in rev.__dict__.items() if not k.startswith("_")},
            "items": [{k: v for k, v in i.__dict__.items() if not k.startswith("_")} for i in items],
            "follow_up_actions": [{k: v for k, v in fa.__dict__.items() if not k.startswith("_")} for fa in fas]}


def get_plan_review(session: Session, plan_id: int) -> dict:
    rev = session.exec(select(WeeklyReview).where(WeeklyReview.weekly_plan_id == plan_id)).first()
    if not rev:
        return {"ok": False, "error": "No review yet"}
    return get_review(session, rev.id)


def submit_user_review(session: Session, review_id: int, data: dict) -> dict:
    rev = session.get(WeeklyReview, review_id)
    if not rev:
        return {"ok": False, "error": "Not found"}
    rev.user_overall_note = data.get("overall_note", "")

    variance_map = data.get("item_variance_reasons", {})
    if isinstance(variance_map, dict):
        for item_id_str, reason in variance_map.items():
            try:
                item_id = int(item_id_str)
                ri = session.exec(select(WeeklyReviewItem).where(
                    WeeklyReviewItem.weekly_review_id == review_id,
                    WeeklyReviewItem.weekly_plan_item_id == item_id)).first()
                if ri and reason:
                    ri.user_variance_reason = reason
                    ri.updated_at = datetime.now()
            except (ValueError, TypeError):
                pass

    if data.get("confirm"):
        rev.status = "USER_CONFIRMED"
        rev.reviewed_at = datetime.now()

    session.commit()
    return {"ok": True, "review_id": review_id, "status": rev.status}


def close_weekly_review(session: Session, review_id: int, data: dict) -> dict:
    rev = session.get(WeeklyReview, review_id)
    if not rev:
        return {"ok": False, "error": "Not found"}
    if rev.status != "USER_CONFIRMED":
        return {"ok": False, "error": "Not yet user-confirmed"}
    if not data.get("confirm_close"):
        return {"ok": False, "error": "confirm_close required"}

    # Check critical open actions
    open_critical = session.exec(select(FollowUpAction).where(
        FollowUpAction.weekly_review_id == review_id,
        FollowUpAction.action_type.in_(("DATA_REPAIR", "EXECUTION_MISSING", "RECONCILIATION_REQUIRED")),
        FollowUpAction.status == "OPEN")).all()
    if open_critical:
        return {"ok": False, "error": f"{len(open_critical)} critical follow-ups still open"}

    # Check unresolved mismatches
    mismatches = session.exec(select(WeeklyReviewItem).where(
        WeeklyReviewItem.weekly_review_id == review_id,
        WeeklyReviewItem.review_category == "EXECUTED_MISMATCH")).all()
    undecided = session.exec(select(WeeklyReviewItem).where(
        WeeklyReviewItem.weekly_review_id == review_id,
        WeeklyReviewItem.review_category == "UNDECIDED")).all()
    if mismatches or undecided:
        return {"ok": False, "error": f"{len(mismatches)} mismatches + {len(undecided)} undecided"}

    rev.status = "CLOSED"; rev.closed_at = datetime.now()
    session.commit()
    return {"ok": True, "review_id": review_id, "status": "CLOSED"}


def get_pending_reviews(session: Session) -> dict:
    reviews = session.exec(select(WeeklyReview).where(
        WeeklyReview.status.in_(("INCOMPLETE", "READY_FOR_USER", "USER_CONFIRMED")))
                           .order_by(WeeklyReview.created_at.desc())).all()
    return {"ok": True, "pending": [{"id": r.id, "plan_id": r.weekly_plan_id, "status": r.status,
                                     "period": f"{r.period_start}~{r.period_end}"} for r in reviews]}


def update_follow_up(session: Session, action_id: int, data: dict) -> dict:
    fa = session.get(FollowUpAction, action_id)
    if not fa:
        return {"ok": False, "error": "Not found"}
    status = data.get("status")
    if status == "DISMISSED":
        fa.status = "DISMISSED"; fa.updated_at = datetime.now()
    elif status == "DONE":
        if not data.get("verification_result", "").strip():
            return {"ok": False, "error": "verification_result required to mark DONE"}
        fa.status = "DONE"; fa.verification_result = data["verification_result"]
        fa.completed_at = datetime.now(); fa.updated_at = datetime.now()
    else:
        return {"ok": False, "error": f"Invalid status: {status}"}
    session.commit()
    return {"ok": True, "action_id": action_id, "status": fa.status}
