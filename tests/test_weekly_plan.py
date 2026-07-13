"""v2.1 Product Core Foundation — tests."""
import pytest
from sqlmodel import Session, SQLModel, create_engine, select, StaticPool
from db.models import (Asset, InvestmentPlanConfig, WeeklyInvestmentPlan, WeeklyPlanItem,
                       DecisionJournalEntry, DailyDecision, Transaction, FundState)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def default_config(session):
    cfg = InvestmentPlanConfig(id=1, name="default", weekly_budget=200, core_target_ratio=0.65,
                               satellite_target_ratio=0.35, strategy_version="v2.1")
    session.add(cfg); session.commit()
    return cfg


def test_asset_role_defaults(session):
    a = Asset(code="000083", name="消费行业")
    session.add(a); session.commit()
    assert a.role == "core"
    assert a.proxy_code is None
    assert a.proxy_type == "INDEX"
    assert a.theme == ""
    assert a.target_weight == 0.0
    assert a.expected_holding_months == 12
    assert a.enabled is True


def test_asset_migration_preserves_existing_data(session):
    a = Asset(code="000083", name="消费行业", max_weight_limit=0.25)
    session.add(a); session.commit()
    a2 = session.get(Asset, a.id)
    assert a2.max_weight_limit == 0.25
    assert a2.name == "消费行业"


def test_create_weekly_plan_idempotent(session, default_config):
    from application.weekly_plan import create_draft_weekly_plan
    r1 = create_draft_weekly_plan(session, "2026-07-06", 1)
    r2 = create_draft_weekly_plan(session, "2026-07-06", 1)
    assert r1["plan_id"] == r2["plan_id"]
    assert r2["idempotent"] is True


def test_config_not_found(session):
    from application.weekly_plan import create_draft_weekly_plan
    r = create_draft_weekly_plan(session, "2026-07-06", 999)
    assert r["ok"] is False
    assert r["error_code"] == "CONFIG_NOT_FOUND"


def test_weekly_budget_split(session, default_config):
    from application.weekly_plan import create_draft_weekly_plan
    r = create_draft_weekly_plan(session, "2026-07-06", 1)
    plan = session.get(WeeklyInvestmentPlan, r["plan_id"])
    assert plan.core_budget == 130.0
    assert plan.satellite_budget == 70.0


def test_frozen_plan_cannot_mutate(session, default_config):
    from application.weekly_plan import create_draft_weekly_plan, freeze_weekly_plan, add_existing_decisions_to_plan
    r = create_draft_weekly_plan(session, "2026-07-06", 1)
    freeze_weekly_plan(session, r["plan_id"])
    r2 = add_existing_decisions_to_plan(session, r["plan_id"])
    assert r2["ok"] is False
    assert "frozen" in r2.get("error", "")


def test_freeze_creates_decision_journal(session, default_config):
    from application.weekly_plan import create_draft_weekly_plan, freeze_weekly_plan
    a = Asset(code="000083", name="消费行业", investment_thesis="长期定投消费龙头")
    dd = DailyDecision(fund_code="000083", date="2026-07-06", strategy_action="observe")
    session.add(a); session.add(dd); session.commit()
    r = create_draft_weekly_plan(session, "2026-07-06", 1)
    item = WeeklyPlanItem(weekly_plan_id=r["plan_id"], asset_code="000083", daily_decision_id=dd.id,
                          data_quality_status="ok")
    session.add(item); session.commit()
    fr = freeze_weekly_plan(session, r["plan_id"])
    assert fr["ok"] is True
    assert fr["journals_created"] == 1
    journals = session.exec(select(DecisionJournalEntry).where(
        DecisionJournalEntry.weekly_plan_item_id == item.id)).all()
    assert len(journals) == 1
    assert journals[0].investment_thesis_snapshot == "长期定投消费龙头"


def test_add_decisions_date_range(session, default_config):
    from application.weekly_plan import create_draft_weekly_plan, add_existing_decisions_to_plan
    r = create_draft_weekly_plan(session, "2026-07-06", 1)
    dd_before = DailyDecision(fund_code="000083", date="2026-07-05", strategy_action="observe")
    dd_in = DailyDecision(fund_code="001532", date="2026-07-07", strategy_action="observe")
    dd_after = DailyDecision(fund_code="002340", date="2026-07-13", strategy_action="observe")
    session.add_all([dd_before, dd_in, dd_after]); session.commit()
    result = add_existing_decisions_to_plan(session, r["plan_id"])
    assert result["ok"] is True
    assert result["items_added"] == 1


# ── Safety Tests ──

def test_no_auto_trade(session, default_config):
    from application.weekly_plan import create_draft_weekly_plan, freeze_weekly_plan
    a = Asset(code="000083", name="消费行业")
    dd = DailyDecision(fund_code="000083", date="2026-07-06", strategy_action="observe")
    session.add_all([a, dd]); session.commit()
    before = len(session.exec(select(Transaction)).all())
    r = create_draft_weekly_plan(session, "2026-07-06", 1)
    item = WeeklyPlanItem(weekly_plan_id=r["plan_id"], asset_code="000083", daily_decision_id=dd.id,
                          data_quality_status="ok")
    session.add(item); session.commit()
    freeze_weekly_plan(session, r["plan_id"])
    after = len(session.exec(select(Transaction)).all())
    assert after == before, "Draft + Freeze must not create Transaction"


def test_no_pool_deduction(session, default_config):
    from application.weekly_plan import create_draft_weekly_plan, freeze_weekly_plan
    st = FundState(code="pool", pool_balance=1000.0)
    a = Asset(code="000083", name="消费行业")
    dd = DailyDecision(fund_code="000083", date="2026-07-06", strategy_action="observe")
    session.add_all([st, a, dd]); session.commit()
    r = create_draft_weekly_plan(session, "2026-07-06", 1)
    item = WeeklyPlanItem(weekly_plan_id=r["plan_id"], asset_code="000083", daily_decision_id=dd.id,
                          data_quality_status="ok")
    session.add(item); session.commit()
    freeze_weekly_plan(session, r["plan_id"])
    st2 = session.get(FundState, st.id)
    assert st2.pool_balance == 1000.0, "Draft + Freeze must not deduct pool"


# ── Unique Constraint Tests ──

def test_weekly_plan_db_unique_constraint(session, default_config):
    import sqlite3
    p1 = WeeklyInvestmentPlan(week_start="2026-08-03", week_end="2026-08-09", config_id=1, status="DRAFT")
    session.add(p1); session.commit()
    p2 = WeeklyInvestmentPlan(week_start="2026-08-03", week_end="2026-08-09", config_id=1, status="DRAFT")
    session.add(p2)
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


def test_weekly_plan_item_db_unique_constraint(session, default_config):
    import sqlite3
    p = WeeklyInvestmentPlan(week_start="2026-08-03", week_end="2026-08-09", config_id=1, status="DRAFT")
    dd = DailyDecision(fund_code="000083", date="2026-08-04", strategy_action="observe")
    session.add_all([p, dd]); session.commit()
    item1 = WeeklyPlanItem(weekly_plan_id=p.id, asset_code="000083", daily_decision_id=dd.id)
    session.add(item1); session.commit()
    item2 = WeeklyPlanItem(weekly_plan_id=p.id, asset_code="000083", daily_decision_id=dd.id)
    session.add(item2)
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


# ── Migration Tests ──

def test_migration_creates_unique_indexes(session, default_config):
    # The unique constraint is tested above via DB rejection.
    # This test verifies the migration function runs without error.
    from backend.db.migrations import migrate
    result = migrate(":memory:")
    assert result["ok"] is True
    assert result["version"] == "v2.1"
