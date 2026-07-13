"""v2.1 Weekly Plan — application layer + calculation pipeline."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, timedelta
from sqlmodel import Session, select
from db.models import (InvestmentPlanConfig, WeeklyInvestmentPlan, WeeklyPlanItem,
                       DecisionJournalEntry, DailyDecision, Asset, MarketSnapshot)


# ═══════════════════════════════════════════════════════════════
# Budget allocation (pure, no DB)
# ═══════════════════════════════════════════════════════════════

def allocate_role_budget(items: list, role_budget: Decimal) -> list:
    """Allocate budget: fixed_first → dynamic_proportional.
    Each item gets allocated_fixed + allocated_dynamic = final_amount."""
    budget = role_budget
    result = []

    # Phase 1: Fixed allocation
    fixed_items = [(Decimal(str(it.get("fixed_amount", 0) or 0)), it) for it in items
                   if it.get("fixed_amount") and it["fixed_amount"] > 0
                   and it.get("candidate_action") not in ("WATCH_ONLY", "BLOCKED", "REVIEW_REQUIRED")]
    fixed_total = sum(amt for amt, _ in fixed_items)
    fixed_scale = Decimal("1") if fixed_total == 0 or fixed_total <= budget else budget / fixed_total

    for amt, it in fixed_items:
        alloc = (amt * fixed_scale).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        it["allocated_fixed"] = float(alloc)
        it["fixed_scale"] = float(fixed_scale)
        budget -= alloc

    # Phase 2: Dynamic allocation (remaining budget)
    dynamic_items = [(Decimal(str(it.get("dynamic_amount", 0) or 0)), it) for it in items
                     if it.get("dynamic_amount") and it["dynamic_amount"] > 0
                     and it.get("candidate_action") not in ("WATCH_ONLY", "BLOCKED", "REVIEW_REQUIRED")]
    dynamic_total = sum(amt for amt, _ in dynamic_items)
    dynamic_scale = Decimal("1") if dynamic_total == 0 or dynamic_total <= budget else budget / dynamic_total

    for amt, it in dynamic_items:
        alloc = (amt * dynamic_scale).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        it["allocated_dynamic"] = float(alloc)
        it["dynamic_scale"] = float(dynamic_scale)
        budget -= alloc

    for it in items:
        af = it.get("allocated_fixed", 0) or 0
        ad = it.get("allocated_dynamic", 0) or 0
        it["requested_fixed"] = it.get("fixed_amount")
        it["requested_dynamic"] = it.get("dynamic_amount")
        it["final_amount"] = float(Decimal(str(af)) + Decimal(str(ad)))
        it["unallocated_budget"] = float(budget)
        it["calculation_trace"] = (it.get("calculation_trace", "") +
                                   f";req_fixed={it.get('fixed_amount')};alloc_fixed={af};"
                                   f"req_dynamic={it.get('dynamic_amount')};alloc_dynamic={ad};"
                                   f"scale_fixed={it.get('fixed_scale',1)};scale_dynamic={it.get('dynamic_scale',1)}")
    return items


# ═══════════════════════════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════════════════════════

def build_weekly_investment_plan(session: Session, week_start: str, config_id: int = 1,
                                 rebuild: bool = False,
                                 adapters: dict = None) -> dict:
    """Orchestrate: config → assets → adapters → budget → guard → plan. Single transaction."""
    if adapters is None:
        from application.adapters.value_dca_adapter import calculate_asset_candidate
        from application.adapters.valuation_adapter import get_valuation_state
        from application.adapters.exposure_guard_adapter import apply_exposure_guard_batch
        adapters = {"value_dca": calculate_asset_candidate, "valuation": get_valuation_state,
                    "exposure_guard": apply_exposure_guard_batch}

    config = session.get(InvestmentPlanConfig, config_id)
    if not config:
        return {"ok": False, "error_code": "CONFIG_NOT_FOUND"}

    existing = session.exec(select(WeeklyInvestmentPlan).where(
        WeeklyInvestmentPlan.week_start == week_start,
        WeeklyInvestmentPlan.config_id == config_id)).first()

    if existing and not rebuild:
        items = session.exec(select(WeeklyPlanItem).where(
            WeeklyPlanItem.weekly_plan_id == existing.id)).all()
        return {"ok": True, "plan_id": existing.id, "status": existing.status,
                "idempotent": True, "items": [model_to_dict(i) for i in items]}

    if existing and rebuild:
        if existing.status != "DRAFT":
            return {"ok": False, "error_code": "CANNOT_REBUILD", "error": f"Plan is {existing.status}"}

    # ── Single transaction ──
    errors = []
    try:
        with session.begin_nested() if hasattr(session, 'begin_nested') else session:
            if existing and rebuild:
                for old in session.exec(select(WeeklyPlanItem).where(
                    WeeklyPlanItem.weekly_plan_id == existing.id)).all():
                    session.delete(old)
                session.flush()
            else:
                week_end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
                existing = WeeklyInvestmentPlan(week_start=week_start, week_end=week_end,
                                                config_id=config_id, strategy_version=config.strategy_version,
                                                available_budget=config.weekly_budget,
                                                core_budget=config.weekly_budget * config.core_target_ratio,
                                                satellite_budget=config.weekly_budget * config.satellite_target_ratio,
                                                status="DRAFT")
                session.add(existing)
                session.flush()

            # Read data
            assets = session.exec(select(Asset).where(Asset.enabled == True)).all()
            markets = {m.asset_code: m for m in session.exec(select(MarketSnapshot)).all()}

            core_items = []
            satellite_items = []

            for asset in assets:
                mkt = markets.get(asset.code)
                if not mkt:
                    errors.append({"asset": asset.code, "error": "NO_MARKET_DATA"})
                    item = _make_error_item(asset, "SOURCE_ERROR")
                    _categorize(item, core_items, satellite_items, asset.role)
                    continue

                # Data quality
                if not mkt.is_trusted or mkt.quality_status != "PASS":
                    dq = "REVIEW_REQUIRED" if not mkt.is_trusted else mkt.quality_status
                else:
                    dq = "PASS"

                # Valuation
                val = adapters["valuation"](asset.code)
                val_state = val.get("valuation_state", "unknown")
                if val.get("valuation_status") in ("SOURCE_ERROR", "DATA_MISSING"):
                    dq = "REVIEW_REQUIRED"

                # Value-DCA
                dca = adapters["value_dca"](asset, mkt, val, config, session)
                if not dca.get("ok"):
                    errors.append({"asset": asset.code, "error": dca.get("error_code", "VALUE_DCA_FAILED")})
                    item = {"asset_code": asset.code, "asset_role": asset.role,
                            "candidate_action": "REVIEW_REQUIRED",
                            "fixed_amount": None, "dynamic_amount": None, "candidate_amount": None,
                            "valuation_state": val_state, "data_quality_status": dq,
                            "calculation_trace": dca.get("error", ""), "risk_status": "FAILED"}
                else:
                    item = {"asset_code": asset.code, "asset_role": asset.role,
                            "fixed_amount": dca["fixed_amount"], "dynamic_amount": dca["dynamic_amount"],
                            "candidate_amount": dca["candidate_amount"],
                            "candidate_action": dca["candidate_action"],
                            "valuation_state": val_state, "data_quality_status": dq,
                            "risk_status": dca.get("risk_status", "ok"),
                            "calculation_trace": dca.get("calculation_trace", "{}")}

                if item["candidate_action"] in ("WATCH_ONLY",):
                    item["candidate_amount"] = None
                _categorize(item, core_items, satellite_items, asset.role)

            # Budget allocation
            core_budget = Decimal(str(config.weekly_budget * config.core_target_ratio))
            sat_budget = Decimal(str(config.weekly_budget * config.satellite_target_ratio))
            core_items = allocate_role_budget(core_items, core_budget)
            satellite_items = allocate_role_budget(satellite_items, sat_budget)

            # Exposure Guard
            all_items = core_items + satellite_items
            candidates = [i for i in all_items if (i.get("final_amount") or 0) > 0]
            if candidates:
                candidates = adapters["exposure_guard"](candidates, session)

            # Merge back
            for ci in candidates:
                for ai in all_items:
                    if ai["asset_code"] == ci["asset_code"]:
                        ai.update({k: v for k, v in ci.items() if k in ("exposure_status", "exposure_reasons", "final_amount", "candidate_action")})
                        if ci.get("exposure_status") == "BLOCKED":
                            ai["final_amount"] = None

            # Write to DB
            total_candidate = Decimal("0")
            total_final = Decimal("0")
            blocked_count = 0
            review_count = 0

            for it in all_items:
                # Data quality gate: hide amounts for non-PASS
                dq = it.get("data_quality_status", "PASS")
                if dq not in ("PASS", "WARNING"):
                    it["candidate_amount"] = None
                    it["final_amount"] = None
                    if dq != "REVIEW_REQUIRED":
                        it["candidate_action"] = "REVIEW_REQUIRED"

                mkt = markets.get(it["asset_code"])
                item = WeeklyPlanItem(weekly_plan_id=existing.id, asset_code=it["asset_code"],
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
                                      # Audit persistence
                                      market_snapshot_id=mkt.id if mkt else None,
                                      market_data_date=str(getattr(mkt, "data_date", "")),
                                      data_source=str(getattr(mkt, "market_source", "")),
                                      proxy_code=str(getattr(mkt, "proxy_code", "")),
                                      dev_pct=float(getattr(mkt, "dev_pct", 0) or 0) if mkt else None,
                                      allocated_fixed=it.get("allocated_fixed"),
                                      allocated_dynamic=it.get("allocated_dynamic"),
                                      exposure_status=it.get("exposure_status", "unknown"),
                                      exposure_reasons=it.get("exposure_reasons", ""),
                                      strategy_version=config.strategy_version)
                session.add(item)
                if it.get("candidate_amount"):
                    total_candidate += Decimal(str(it["candidate_amount"]))
                if it.get("final_amount"):
                    total_final += Decimal(str(it["final_amount"]))
                if it.get("exposure_status") == "BLOCKED":
                    blocked_count += 1
                if it.get("candidate_action") == "REVIEW_REQUIRED":
                    review_count += 1

            existing.data_quality_status = "REVIEW_REQUIRED" if errors else "PASS"
            existing.exposure_status = "REVIEW_REQUIRED" if blocked_count > 0 or review_count > 0 else "PASS"
            existing.blocked_item_count = blocked_count
            existing.review_required_item_count = review_count
            existing.total_candidate_amount = float(total_candidate)
            existing.total_final_amount = float(total_final)
            existing.unallocated_core_budget = float(core_budget - sum(
                Decimal(str(it.get("final_amount", 0) or 0)) for it in core_items))
            existing.unallocated_satellite_budget = float(sat_budget - sum(
                Decimal(str(it.get("final_amount", 0) or 0)) for it in satellite_items))

            session.commit()

    except Exception as e:
        session.rollback()
        return {"ok": False, "error_code": "BUILD_FAILED", "error": str(e)[:300]}

    items = session.exec(select(WeeklyPlanItem).where(
        WeeklyPlanItem.weekly_plan_id == existing.id)).all()
    return {"ok": True, "plan_id": existing.id, "status": existing.status,
            "errors": errors, "blocked_items": blocked_count, "review_required_items": review_count,
            "total_candidate": float(total_candidate), "total_final": float(total_final),
            "items": [model_to_dict(i) for i in items]}


def _categorize(item, core_items, satellite_items, role):
    if role == "satellite":
        satellite_items.append(item)
    else:
        core_items.append(item)


def _make_error_item(asset, dq_status):
    return {"asset_code": asset.code, "asset_role": asset.role, "candidate_action": "REVIEW_REQUIRED",
            "fixed_amount": None, "dynamic_amount": None, "candidate_amount": None,
            "valuation_state": "unknown", "data_quality_status": dq_status,
            "calculation_trace": "NO_MARKET_DATA", "risk_status": "FAILED"}


# ═══════════════════════════════════════════════════════════════
# Existing helpers (unchanged)
# ═══════════════════════════════════════════════════════════════

def create_draft_weekly_plan(session, week_start="", config_id=1):
    if not week_start:
        today = date.today()
        week_start = (today - timedelta(days=today.weekday())).isoformat()
    week_end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
    existing = session.exec(select(WeeklyInvestmentPlan).where(
        WeeklyInvestmentPlan.week_start == week_start, WeeklyInvestmentPlan.config_id == config_id)).first()
    if existing:
        return {"ok": True, "plan_id": existing.id, "status": existing.status, "idempotent": True}
    config = session.get(InvestmentPlanConfig, config_id)
    if not config:
        return {"ok": False, "error_code": "CONFIG_NOT_FOUND"}
    plan = WeeklyInvestmentPlan(week_start=week_start, week_end=week_end, config_id=config_id,
                                strategy_version=config.strategy_version,
                                available_budget=config.weekly_budget,
                                core_budget=config.weekly_budget * config.core_target_ratio,
                                satellite_budget=config.weekly_budget * config.satellite_target_ratio, status="DRAFT")
    session.add(plan); session.commit(); session.refresh(plan)
    return {"ok": True, "plan_id": plan.id, "status": "DRAFT", "idempotent": False}


def add_existing_decisions_to_plan(session, plan_id, date_str=""):
    plan = session.get(WeeklyInvestmentPlan, plan_id)
    if not plan:
        return {"ok": False, "error": "Plan not found"}
    if plan.status != "DRAFT":
        return {"ok": False, "error": "Plan is frozen"}
    decisions = session.exec(select(DailyDecision).where(
        DailyDecision.date >= plan.week_start, DailyDecision.date <= plan.week_end)).all()
    assets = {a.code: a for a in session.exec(select(Asset)).all()}
    added = 0
    for dd in decisions:
        existing = session.exec(select(WeeklyPlanItem).where(
            WeeklyPlanItem.weekly_plan_id == plan_id, WeeklyPlanItem.daily_decision_id == dd.id)).first()
        if existing:
            continue
        asset = assets.get(dd.fund_code)
        item = WeeklyPlanItem(weekly_plan_id=plan_id, asset_code=dd.fund_code,
                              asset_role=getattr(asset, 'role', 'core'), daily_decision_id=dd.id,
                              action=dd.strategy_action or "NO_ACTION",
                              risk_status=dd.system_status or "ok", data_quality_status="unknown")
        session.add(item); added += 1
    session.commit()
    return {"ok": True, "plan_id": plan_id, "items_added": added}


def freeze_weekly_plan(session, plan_id):
    plan = session.get(WeeklyInvestmentPlan, plan_id)
    if not plan:
        return {"ok": False, "error": "Not found"}
    if plan.status != "DRAFT":
        return {"ok": False, "error": f"Cannot freeze status={plan.status}"}
    items = session.exec(select(WeeklyPlanItem).where(WeeklyPlanItem.weekly_plan_id == plan_id)).all()
    for item in items:
        if item.data_quality_status == "unknown":
            return {"ok": False, "error": f"Item {item.id} has unknown data_quality_status"}
    plan.status = "FROZEN"
    plan.frozen_at = datetime.now()
    journals = 0
    for item in items:
        journal = DecisionJournalEntry(
            weekly_plan_item_id=item.id,
            investment_thesis_snapshot="",
            expected_scenario=item.valuation_state or "",
            invalidation_conditions="",
            known_unknowns="Top10-only暴露, 估值代理可能偏弱",
            immutable=True,
            strategy_version=plan.strategy_version,
            valuation_state=item.valuation_state or "",
            fixed_amount=item.fixed_amount, dynamic_amount=item.dynamic_amount,
            candidate_amount=item.candidate_amount, final_amount=item.final_amount,
            risk_status=item.risk_status or "", exposure_status="",
            calculation_trace=item.calculation_trace or "",
            evidence_json=str({"asset_code": item.asset_code, "action": item.action}),
            market_data_date=item.market_data_date or "",
            data_source=item.data_source or "",
            proxy_code=item.proxy_code or "",
            exposure_status=item.exposure_status or "unknown",
        )
        session.add(journal); journals += 1
    session.commit()
    return {"ok": True, "plan_id": plan_id, "status": "FROZEN", "journals_created": journals}


def get_weekly_plan(session, plan_id):
    plan = session.get(WeeklyInvestmentPlan, plan_id)
    if not plan:
        return {"ok": False, "error": "Not found"}
    items = session.exec(select(WeeklyPlanItem).where(WeeklyPlanItem.weekly_plan_id == plan_id)).all()
    return {"ok": True, "plan": model_to_dict(plan), "items": [model_to_dict(i) for i in items]}


def list_weekly_plans(session, limit=10):
    plans = session.exec(select(WeeklyInvestmentPlan).order_by(
        WeeklyInvestmentPlan.created_at.desc()).limit(limit)).all()
    return {"ok": True, "plans": [{"id": p.id, "week_start": p.week_start, "status": p.status} for p in plans]}


def model_to_dict(model):
    return {k: v for k, v in model.__dict__.items() if not k.startswith('_')}
