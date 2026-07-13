"""v2.1 Weekly Plan — application layer + calculation pipeline."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, timedelta
from sqlmodel import Session, select
from db.models import (InvestmentPlanConfig, WeeklyInvestmentPlan, WeeklyPlanItem,
                       DecisionJournalEntry, DailyDecision, Asset, FundHoldingSnapshot)


# ═══════════════════════════════════════════════════════════════
# Budget allocation (pure function, no DB)
# ═══════════════════════════════════════════════════════════════

def allocate_role_budget(items: list, role_budget: Decimal) -> list:
    """Pure function. Allocate budget to items by priority: fixed → dynamic."""
    budget = role_budget
    fixed_items = []
    dynamic_items = []
    other_items = []

    for it in items:
        action = it.get("candidate_action", "")
        if it.get("candidate_amount") is None or action in ("WATCH_ONLY", "BLOCKED", "REVIEW_REQUIRED"):
            other_items.append(it)
            continue
        if it.get("fixed_amount") and it["fixed_amount"] > 0:
            fixed_items.append(it)
        elif it.get("dynamic_amount") and it["dynamic_amount"] > 0:
            dynamic_items.append(it)
        else:
            other_items.append(it)

    # Phase 1: Fixed amounts at full face
    fixed_total = sum(Decimal(str(it["fixed_amount"])) for it in fixed_items)
    for it in fixed_items:
        fa = Decimal(str(it["fixed_amount"]))
        if fixed_total > budget:
            scale = budget / fixed_total
            it["final_amount"] = float((fa * scale).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            it["scaled"] = True
        else:
            it["final_amount"] = it["fixed_amount"]
        it["calculation_trace"] = (it.get("calculation_trace", "") + f";fixed_alloc={it['final_amount']}")

    # Phase 2: Dynamic amounts use remaining budget
    remaining = budget - sum(Decimal(str(it["final_amount"])) for it in fixed_items)
    if remaining <= 0:
        for it in dynamic_items:
            it["final_amount"] = 0
        return fixed_items + dynamic_items + other_items

    dynamic_total = sum(Decimal(str(it["dynamic_amount"])) for it in dynamic_items)
    for it in dynamic_items:
        da = Decimal(str(it["dynamic_amount"]))
        if dynamic_total > remaining:
            scale = remaining / dynamic_total
            it["final_amount"] = float((da * scale).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        else:
            it["final_amount"] = it["dynamic_amount"]
        it["calculation_trace"] = (it.get("calculation_trace", "") + f";dyn_alloc={it['final_amount']}")

    return fixed_items + dynamic_items + other_items


# ═══════════════════════════════════════════════════════════════
# Data quality assessment (pure function)
# ═══════════════════════════════════════════════════════════════

def assess_data_quality(nav, ma200, has_snapshot, is_fixture) -> str:
    """Return PASS / WARNING / REVIEW_REQUIRED / BLOCKED / SOURCE_ERROR."""
    if nav is None or ma200 is None:
        return "SOURCE_ERROR"
    if is_fixture:
        return "WARNING"
    if not has_snapshot:
        return "WARNING"
    return "PASS"


# ═══════════════════════════════════════════════════════════════
# Main pipeline: build_weekly_investment_plan
# ═══════════════════════════════════════════════════════════════

def build_weekly_investment_plan(session: Session, week_start: str, config_id: int = 1,
                                 rebuild: bool = False) -> dict:
    """Orchestrate the full Weekly Plan calculation pipeline."""
    # 1. Read config
    config = session.get(InvestmentPlanConfig, config_id)
    if not config:
        return {"ok": False, "error_code": "CONFIG_NOT_FOUND"}

    # 2. Idempotent: return existing if not rebuild
    existing = session.exec(select(WeeklyInvestmentPlan).where(
        WeeklyInvestmentPlan.week_start == week_start,
        WeeklyInvestmentPlan.config_id == config_id
    )).first()

    if existing and not rebuild:
        items = session.exec(select(WeeklyPlanItem).where(
            WeeklyPlanItem.weekly_plan_id == existing.id)).all()
        return {"ok": True, "plan_id": existing.id, "status": existing.status,
                "idempotent": True, "items": [_model_to_dict(i) for i in items]}

    if existing and rebuild:
        if existing.status != "DRAFT":
            return {"ok": False, "error_code": "CANNOT_REBUILD", "error": f"Plan is {existing.status}"}
        # Delete old items
        for item in session.exec(select(WeeklyPlanItem).where(
            WeeklyPlanItem.weekly_plan_id == existing.id)).all():
            session.delete(item)
        session.commit()
    else:
        # Create new plan
        week_end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
        existing = WeeklyInvestmentPlan(week_start=week_start, week_end=week_end,
                                        config_id=config_id, strategy_version=config.strategy_version,
                                        available_budget=config.weekly_budget,
                                        core_budget=config.weekly_budget * config.core_target_ratio,
                                        satellite_budget=config.weekly_budget * config.satellite_target_ratio,
                                        status="DRAFT")
        session.add(existing)
        session.commit()
        session.refresh(existing)

    # 3. Read all enabled assets
    assets = session.exec(select(Asset).where(Asset.enabled == True)).all()
    snapshots = {s.fund_code: s for s in session.exec(select(FundHoldingSnapshot)).all()}

    core_items = []
    satellite_items = []
    errors = []

    for asset in assets:
        snap = snapshots.get(asset.code)
        has_snapshot = snap is not None and not getattr(snap, "is_fixture", False)
        is_fixture = getattr(snap, "is_fixture", False)

        # Data quality
        dq = assess_data_quality(
            getattr(snap, "nav", None) if snap else None,
            getattr(snap, "ma200", None) if snap else None,
            has_snapshot,
            is_fixture,
        )

        # Valuation
        from services.valuation import PROXY_MAP
        proxy = PROXY_MAP.get(asset.code, {})
        val_state = proxy.get("status", "unknown")

        # Value-DCA — avoid circular import
        try:
            from services.value_dca import evaluate_fund
            dca_result = evaluate_fund(asset.code, session) or {}
        except Exception:
            dca_result = {}

        candidate_action = dca_result.get("strategy_action", dca_result.get("action", "NO_ACTION"))
        fixed_amt = dca_result.get("fixed_amount")
        dynamic_amt = dca_result.get("dynamic_amount")
        candidate_amt = dca_result.get("candidate_amount")

        # Apply data quality overrides
        if dq == "BLOCKED" or dq == "SOURCE_ERROR":
            candidate_action = "REVIEW_REQUIRED"
            fixed_amt = None
            dynamic_amt = None
            candidate_amt = None
        if candidate_action in ("WATCH_ONLY", "observe", "take_profit_watch"):
            candidate_amt = None

        item_data = {
            "asset_code": asset.code,
            "asset_role": asset.role,
            "candidate_action": candidate_action,
            "fixed_amount": fixed_amt,
            "dynamic_amount": dynamic_amt,
            "candidate_amount": candidate_amt,
            "valuation_state": val_state,
            "data_quality_status": dq,
            "risk_status": dca_result.get("system_status", "ok"),
            "calculation_trace": dca_result.get("calculation_trace", "{}"),
            "exposure_status": "ok",
        }

        if dq == "SOURCE_ERROR":
            errors.append({"asset": asset.code, "error": "SOURCE_ERROR"})

        if asset.role == "satellite":
            satellite_items.append(item_data)
        else:
            core_items.append(item_data)

    # 4. Budget allocation
    core_budget = Decimal(str(config.weekly_budget * config.core_target_ratio))
    satellite_budget = Decimal(str(config.weekly_budget * config.satellite_target_ratio))

    core_items = allocate_role_budget(core_items, core_budget)
    satellite_items = allocate_role_budget(satellite_items, satellite_budget)

    # 5. Exposure Guard
    all_items = core_items + satellite_items
    for it in all_items:
        # Only apply guard when there's a positive candidate
        if it.get("candidate_amount") and it["candidate_amount"] > 0:
            try:
                from services.exposure_guard import check_exposure
                guard = check_exposure(it["asset_code"], it["candidate_amount"], session) or {}
                if guard.get("blocked"):
                    it["candidate_action"] = "REVIEW_REQUIRED"
                    it["final_amount"] = None
                    it["exposure_status"] = "BLOCKED"
                    it["exposure_reasons"] = guard.get("reasons", "")
                elif guard.get("final_amount") is not None and guard["final_amount"] < it.get("final_amount", 0):
                    it["final_amount"] = guard["final_amount"]  # can only decrease
                    it["exposure_status"] = "REDUCED"
                    it["exposure_reasons"] = guard.get("reasons", "")
            except Exception:
                pass  # Exposure guard failure → keep prior result

    # 6. Write to DB
    total_candidate = Decimal("0")
    total_final = Decimal("0")
    blocked_count = 0
    review_count = 0

    for it in all_items:
        item = WeeklyPlanItem(
            weekly_plan_id=existing.id, asset_code=it["asset_code"],
            asset_role=it["asset_role"],
            fixed_amount=it.get("fixed_amount"),
            dynamic_amount=it.get("dynamic_amount"),
            candidate_amount=it.get("candidate_amount"),
            final_amount=it.get("final_amount"),
            action=it.get("candidate_action", "NO_ACTION"),
            valuation_state=it.get("valuation_state", "unknown"),
            risk_status=it.get("risk_status", "ok"),
            data_quality_status=it.get("data_quality_status", "unknown"),
            calculation_trace=str(it.get("calculation_trace", "{}")),
            reason_summary=it.get("exposure_reasons", ""),
        )
        session.add(item)
        if it.get("candidate_amount"):
            total_candidate += Decimal(str(it["candidate_amount"]))
        if it.get("final_amount"):
            total_final += Decimal(str(it["final_amount"]))
        if it.get("exposure_status") == "BLOCKED":
            blocked_count += 1
        if it.get("candidate_action") == "REVIEW_REQUIRED":
            review_count += 1

    # 7. Update plan summary
    existing.data_quality_status = "REVIEW_REQUIRED" if errors else "PASS"
    existing.exposure_status = "REVIEW_REQUIRED" if blocked_count > 0 or review_count > 0 else "PASS"
    existing.blocked_item_count = blocked_count
    existing.review_required_item_count = review_count
    existing.total_candidate_amount = float(total_candidate)
    existing.total_final_amount = float(total_final)
    existing.unallocated_core_budget = float(core_budget - sum(
        Decimal(str(it.get("final_amount", 0) or 0)) for it in core_items))
    existing.unallocated_satellite_budget = float(satellite_budget - sum(
        Decimal(str(it.get("final_amount", 0) or 0)) for it in satellite_items))
    session.commit()

    items = session.exec(select(WeeklyPlanItem).where(
        WeeklyPlanItem.weekly_plan_id == existing.id)).all()
    return {"ok": True, "plan_id": existing.id, "status": existing.status,
            "blocked_items": blocked_count, "review_required_items": review_count,
            "total_candidate": float(total_candidate), "total_final": float(total_final),
            "items": [_model_to_dict(i) for i in items]}


# ═══════════════════════════════════════════════════════════════
# Helpers (kept from original skeleton)
# ═══════════════════════════════════════════════════════════════

def create_draft_weekly_plan(session: Session, week_start: str = "", config_id: int = 1) -> dict:
    if not week_start:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        week_start = monday.isoformat()
    week_end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()

    existing = session.exec(select(WeeklyInvestmentPlan).where(
        WeeklyInvestmentPlan.week_start == week_start,
        WeeklyInvestmentPlan.config_id == config_id
    )).first()
    if existing:
        return {"ok": True, "plan_id": existing.id, "status": existing.status, "idempotent": True}

    config = session.get(InvestmentPlanConfig, config_id)
    if not config:
        return {"ok": False, "error_code": "CONFIG_NOT_FOUND", "error": f"Config id={config_id} does not exist"}
    plan = WeeklyInvestmentPlan(week_start=week_start, week_end=week_end, config_id=config_id,
                                strategy_version=config.strategy_version,
                                available_budget=config.weekly_budget,
                                core_budget=config.weekly_budget * config.core_target_ratio,
                                satellite_budget=config.weekly_budget * config.satellite_target_ratio,
                                status="DRAFT")
    session.add(plan); session.commit(); session.refresh(plan)
    return {"ok": True, "plan_id": plan.id, "status": "DRAFT", "idempotent": False}


def add_existing_decisions_to_plan(session: Session, plan_id: int, date_str: str = "") -> dict:
    plan = session.get(WeeklyInvestmentPlan, plan_id)
    if not plan:
        return {"ok": False, "error": "Plan not found"}
    if plan.status != "DRAFT":
        return {"ok": False, "error": "Plan is frozen, cannot add items"}
    decisions = session.exec(select(DailyDecision).where(
        DailyDecision.date >= plan.week_start,
        DailyDecision.date <= plan.week_end
    )).all()
    assets = {a.code: a for a in session.exec(select(Asset)).all()}
    added = 0
    for dd in decisions:
        existing = session.exec(select(WeeklyPlanItem).where(
            WeeklyPlanItem.weekly_plan_id == plan_id,
            WeeklyPlanItem.daily_decision_id == dd.id
        )).first()
        if existing:
            continue
        asset = assets.get(dd.fund_code)
        item = WeeklyPlanItem(weekly_plan_id=plan_id, asset_code=dd.fund_code,
                              asset_role=getattr(asset, 'role', 'core'),
                              daily_decision_id=dd.id,
                              action=dd.strategy_action or "NO_ACTION",
                              risk_status=dd.system_status or "ok",
                              data_quality_status="unknown")
        session.add(item)
        added += 1
    session.commit()
    return {"ok": True, "plan_id": plan_id, "items_added": added}


def freeze_weekly_plan(session: Session, plan_id: int) -> dict:
    plan = session.get(WeeklyInvestmentPlan, plan_id)
    if not plan:
        return {"ok": False, "error": "Not found"}
    if plan.status != "DRAFT":
        return {"ok": False, "error": f"Cannot freeze status={plan.status}"}
    items = session.exec(select(WeeklyPlanItem).where(
        WeeklyPlanItem.weekly_plan_id == plan_id)).all()
    for item in items:
        if item.data_quality_status == "unknown":
            return {"ok": False, "error": f"Item {item.id} ({item.asset_code}) has unknown data_quality_status"}
    plan.status = "FROZEN"
    plan.frozen_at = datetime.now()
    assets = {a.code: a for a in session.exec(select(Asset)).all()}
    journals = 0
    for item in items:
        asset = assets.get(item.asset_code)
        journal = DecisionJournalEntry(
            weekly_plan_item_id=item.id,
            investment_thesis_snapshot=getattr(asset, 'investment_thesis', ''),
            expected_scenario=getattr(item, 'valuation_state', ''),
            invalidation_conditions=getattr(asset, 'invalidation_conditions', ''),
            known_unknowns="Top10-only暴露, 估值代理可能偏弱",
            immutable=True,
        )
        session.add(journal)
        journals += 1
    session.commit()
    return {"ok": True, "plan_id": plan_id, "status": "FROZEN", "journals_created": journals}


def get_weekly_plan(session: Session, plan_id: int) -> dict:
    plan = session.get(WeeklyInvestmentPlan, plan_id)
    if not plan:
        return {"ok": False, "error": "Not found"}
    items = session.exec(select(WeeklyPlanItem).where(
        WeeklyPlanItem.weekly_plan_id == plan_id)).all()
    return {"ok": True, "plan": _model_to_dict(plan), "items": [_model_to_dict(i) for i in items]}


def list_weekly_plans(session: Session, limit: int = 10) -> dict:
    plans = session.exec(select(WeeklyInvestmentPlan).order_by(
        WeeklyInvestmentPlan.created_at.desc()).limit(limit)).all()
    return {"ok": True, "plans": [{"id": p.id, "week_start": p.week_start, "status": p.status} for p in plans]}


def _model_to_dict(model):
    return {k: v for k, v in model.__dict__.items() if not k.startswith('_')}
