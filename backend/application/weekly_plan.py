"""v2.1 Weekly Plan — application layer skeleton."""
from datetime import date, datetime, timedelta
from sqlmodel import Session, select
from db.models import (InvestmentPlanConfig, WeeklyInvestmentPlan, WeeklyPlanItem,
                       DecisionJournalEntry, DailyDecision, Asset)


def create_draft_weekly_plan(session: Session, week_start: str = "", config_id: int = 1) -> dict:
    """Idempotent: create a Draft plan for the given week_start + config_id."""
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
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return {"ok": True, "plan_id": plan.id, "status": "DRAFT", "idempotent": False}


def add_existing_decisions_to_plan(session: Session, plan_id: int, date_str: str = "") -> dict:
    """Link today's DailyDecisions to a WeeklyPlan."""
    plan = session.get(WeeklyInvestmentPlan, plan_id)
    if not plan:
        return {"ok": False, "error": "Plan not found"}
    if plan.status != "DRAFT":
        return {"ok": False, "error": "Plan is frozen, cannot add items"}

    # Bind decisions within the plan's week range
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
    """Freeze plan: make immutable, generate DecisionJournalEntry for each item."""
    plan = session.get(WeeklyInvestmentPlan, plan_id)
    if not plan:
        return {"ok": False, "error": "Not found"}
    if plan.status != "DRAFT":
        return {"ok": False, "error": f"Cannot freeze status={plan.status}"}

    items = session.exec(select(WeeklyPlanItem).where(
        WeeklyPlanItem.weekly_plan_id == plan_id)).all()

    # Check data quality
    for item in items:
        if item.data_quality_status == "unknown":
            return {"ok": False, "error": f"Item {item.id} ({item.asset_code}) has unknown data_quality_status"}

    # Freeze
    plan.status = "FROZEN"
    plan.frozen_at = datetime.now()

    # Generate DecisionJournalEntry for each item
    assets = {a.code: a for a in session.exec(select(Asset)).all()}
    journals = 0
    for item in items:
        asset = assets.get(item.asset_code)
        journal = DecisionJournalEntry(
            weekly_plan_item_id=item.id,
            investment_thesis_snapshot=getattr(asset, 'investment_thesis', ''),
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
    return {"ok": True, "plan": model_to_dict(plan), "items": [model_to_dict(i) for i in items]}


def list_weekly_plans(session: Session, limit: int = 10) -> dict:
    plans = session.exec(select(WeeklyInvestmentPlan).order_by(
        WeeklyInvestmentPlan.created_at.desc()).limit(limit)).all()
    return {"ok": True, "plans": [{"id": p.id, "week_start": p.week_start, "status": p.status} for p in plans]}


def model_to_dict(model):
    """Convert SQLModel instance to dict, skip private attrs."""
    return {k: v for k, v in model.__dict__.items() if not k.startswith('_')}
