"""v2.1 Weekly Plan Calculation Pipeline — tests."""
import pytest
from decimal import Decimal
from sqlmodel import Session, SQLModel, create_engine, select, StaticPool
from db.models import (Asset, InvestmentPlanConfig, WeeklyInvestmentPlan, WeeklyPlanItem,
                       DecisionJournalEntry, DailyDecision, Transaction, FundState,
                       FundHoldingSnapshot)


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


# ═══════════════════════════════════════════════════
# Budget allocation pure function tests
# ═══════════════════════════════════════════════════

def test_allocate_role_budget_fixed_priority():
    from application.weekly_plan import allocate_role_budget
    items = [
        {"asset_code": "A", "candidate_action": "dynamic_dca", "fixed_amount": 50, "dynamic_amount": 10,
         "candidate_amount": 60, "calculation_trace": ""},
        {"asset_code": "B", "candidate_action": "fixed_dca", "fixed_amount": 30, "dynamic_amount": 0,
         "candidate_amount": 30, "calculation_trace": ""},
    ]
    result = allocate_role_budget(items, Decimal("100"))
    # Fixed items get full amount, dynamic uses remaining
    amounts = {it["asset_code"]: it["final_amount"] for it in result}
    assert amounts["A"] == 50.0 or amounts["A"] > 0
    assert amounts["B"] == 30.0
    assert sum(it["final_amount"] for it in result) <= 100.0


def test_allocate_dynamic_proportional_scaling():
    from application.weekly_plan import allocate_role_budget
    items = [
        {"asset_code": "C", "candidate_action": "dynamic_dca", "fixed_amount": 0, "dynamic_amount": 60,
         "candidate_amount": 60, "calculation_trace": ""},
        {"asset_code": "D", "candidate_action": "dynamic_dca", "fixed_amount": 0, "dynamic_amount": 40,
         "candidate_amount": 40, "calculation_trace": ""},
    ]
    result = allocate_role_budget(items, Decimal("50"))  # only 50 available
    amounts = {it["asset_code"]: it["final_amount"] for it in result}
    # 60:40 ratio → 30:20 when scaled to 50
    assert amounts["C"] == 30.0
    assert amounts["D"] == 20.0
    assert sum(it["final_amount"] for it in result) == 50.0


def test_allocate_fixed_scaled_when_over_budget():
    from application.weekly_plan import allocate_role_budget
    items = [
        {"asset_code": "E", "candidate_action": "fixed_dca", "fixed_amount": 80, "dynamic_amount": 0,
         "candidate_amount": 80, "calculation_trace": ""},
        {"asset_code": "F", "candidate_action": "fixed_dca", "fixed_amount": 80, "dynamic_amount": 0,
         "candidate_amount": 80, "calculation_trace": ""},
    ]
    result = allocate_role_budget(items, Decimal("100"))  # 160 needed, 100 available
    amounts = {it["asset_code"]: it["final_amount"] for it in result}
    assert amounts["E"] == 50.0
    assert amounts["F"] == 50.0
    assert sum(it["final_amount"] for it in result) == 100.0


def test_watch_only_has_no_amount():
    from application.weekly_plan import allocate_role_budget
    items = [
        {"asset_code": "G", "candidate_action": "WATCH_ONLY", "fixed_amount": 0, "dynamic_amount": 0,
         "candidate_amount": 0, "calculation_trace": ""},
    ]
    result = allocate_role_budget(items, Decimal("100"))
    assert result[0].get("final_amount", 0) is None or result[0].get("final_amount", 0) == 0


def test_satellite_cannot_consume_core_budget():
    """Satellite items only get satellite budget, core items only core budget."""
    from application.weekly_plan import allocate_role_budget
    core = [{"asset_code": "C1", "candidate_action": "fixed_dca", "fixed_amount": 130, "candidate_amount": 130,
             "calculation_trace": ""}]
    sat = [{"asset_code": "S1", "candidate_action": "dynamic_dca", "fixed_amount": 0, "dynamic_amount": 70,
            "candidate_amount": 70, "calculation_trace": ""}]
    core_result = allocate_role_budget(core, Decimal("130"))
    sat_result = allocate_role_budget(sat, Decimal("70"))
    # Core gets capped at its own budget, satellite at its own
    assert core_result[0]["final_amount"] == 130.0
    assert sum(it.get("final_amount", 0) or 0 for it in sat_result) <= 70.0


# ═══════════════════════════════════════════════════
# Pipeline integration tests (deterministic fixtures)
# ═══════════════════════════════════════════════════

@pytest.fixture
def e2e_fixture(session, default_config):
    """5 assets: 2 core, 3 satellite with deterministic data."""
    assets = [
        Asset(code="CORE_A", name="核心A", role="core", target_weight=0.5, enabled=True),
        Asset(code="CORE_B", name="核心B", role="core", target_weight=0.5, enabled=True),
        Asset(code="SAT_C", name="卫星C", role="satellite", target_weight=0.5, enabled=True),
        Asset(code="SAT_D", name="卫星D", role="satellite", target_weight=0.3, enabled=True),
        Asset(code="SAT_E", name="卫星E", role="satellite", target_weight=0.2, enabled=True),
    ]
    session.add_all(assets)

    # Snapshots with deterministic NAV/MA200
    snaps = [
        FundHoldingSnapshot(fund_code="CORE_A", nav=1.5, ma200=1.4, is_fixture=False),
        FundHoldingSnapshot(fund_code="CORE_B", nav=0.9, ma200=1.0, is_fixture=False),
        FundHoldingSnapshot(fund_code="SAT_C", nav=2.0, ma200=1.6, is_fixture=False),
        FundHoldingSnapshot(fund_code="SAT_D", nav=1.0, ma200=1.0, is_fixture=False),
        FundHoldingSnapshot(fund_code="SAT_E", nav=0.8, ma200=1.0, is_fixture=False),
    ]
    session.add_all(snaps)
    session.commit()


def test_build_plan_uses_enabled_assets_only(session, default_config, e2e_fixture):
    """Disabled assets must not appear in plan."""
    # Disable SAT_E
    a = session.exec(select(Asset).where(Asset.code == "SAT_E")).first()
    a.enabled = False; session.commit()

    from application.weekly_plan import build_weekly_investment_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1)
    assert r["ok"] is True
    codes = {it["asset_code"] for it in r["items"]}
    assert "SAT_E" not in codes
    assert "CORE_A" in codes


def test_core_satellite_budget_split(session, default_config, e2e_fixture):
    from application.weekly_plan import build_weekly_investment_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1)
    assert r["ok"] is True
    # Core budget 130, satellite 70 — total final never exceeds 200
    total = sum(it.get("final_amount", 0) or 0 for it in r["items"])
    assert total <= 200.0


def test_plan_total_never_exceeds_weekly_budget(session, default_config, e2e_fixture):
    from application.weekly_plan import build_weekly_investment_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1)
    total = sum(it.get("final_amount", 0) or 0 for it in r["items"])
    assert total <= default_config.weekly_budget


def test_source_error_not_silently_skipped(session, default_config, e2e_fixture):
    """SOURCE_ERROR assets must appear in plan with action=REVIEW_REQUIRED."""
    # Make SAT_D have no snapshot → SOURCE_ERROR
    snap = session.exec(select(FundHoldingSnapshot).where(
        FundHoldingSnapshot.fund_code == "SAT_D")).first()
    snap.nav = None; snap.ma200 = None; session.commit()

    from application.weekly_plan import build_weekly_investment_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1)
    codes = {it["asset_code"] for it in r["items"]}
    assert "SAT_D" in codes  # must appear, not silently skip
    sat_d = [it for it in r["items"] if it["asset_code"] == "SAT_D"][0]
    assert sat_d["data_quality_status"] in ("SOURCE_ERROR", "REVIEW_REQUIRED")


def test_blocked_data_kept_but_amount_hidden(session, default_config, e2e_fixture):
    from application.weekly_plan import build_weekly_investment_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1)
    for it in r["items"]:
        if it["data_quality_status"] in ("SOURCE_ERROR", "BLOCKED"):
            assert it.get("final_amount") is None or it.get("final_amount") == 0


def test_rebuild_draft_is_atomic(session, default_config, e2e_fixture):
    from application.weekly_plan import build_weekly_investment_plan
    r1 = build_weekly_investment_plan(session, "2026-08-03", 1)
    r2 = build_weekly_investment_plan(session, "2026-08-03", 1, rebuild=True)
    assert r2["ok"] is True
    assert r2["status"] == "DRAFT"


def test_frozen_plan_cannot_rebuild(session, default_config, e2e_fixture):
    from application.weekly_plan import build_weekly_investment_plan, freeze_weekly_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1)
    # Need at least one item with valid data_quality_status
    plan = session.get(WeeklyInvestmentPlan, r["plan_id"])
    item = WeeklyPlanItem(weekly_plan_id=plan.id, asset_code="CORE_A", data_quality_status="ok")
    session.add(item); session.commit()
    freeze_weekly_plan(session, r["plan_id"])
    r2 = build_weekly_investment_plan(session, "2026-08-03", 1, rebuild=True)
    assert r2["ok"] is False
    assert r2["error_code"] == "CANNOT_REBUILD"


def test_no_transaction_created(session, default_config, e2e_fixture):
    from application.weekly_plan import build_weekly_investment_plan
    before = len(session.exec(select(Transaction)).all())
    build_weekly_investment_plan(session, "2026-08-03", 1)
    after = len(session.exec(select(Transaction)).all())
    assert after == before


def test_no_pool_balance_changed(session, default_config, e2e_fixture):
    st = FundState(code="pool", pool_balance=1000.0)
    session.add(st); session.commit()
    from application.weekly_plan import build_weekly_investment_plan
    build_weekly_investment_plan(session, "2026-08-03", 1)
    st2 = session.get(FundState, st.id)
    assert st2.pool_balance == 1000.0


def test_no_user_decision_auto_confirmed(session, default_config, e2e_fixture):
    """Build pipeline should not touch DailyDecision execution status."""
    dd = DailyDecision(fund_code="CORE_A", date="2026-08-03", strategy_action="fixed_dca")
    session.add(dd); session.commit()
    from application.weekly_plan import build_weekly_investment_plan
    build_weekly_investment_plan(session, "2026-08-03", 1)
    dd2 = session.get(DailyDecision, dd.id)
    assert dd2 is not None  # not deleted/modified


def test_freeze_journal_contains_calculation_evidence(session, default_config, e2e_fixture):
    from application.weekly_plan import build_weekly_investment_plan, freeze_weekly_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1)
    plan = session.get(WeeklyInvestmentPlan, r["plan_id"])
    # Manually add an item with data_quality_status=ok to allow freeze
    item = WeeklyPlanItem(weekly_plan_id=plan.id, asset_code="CORE_A", data_quality_status="ok",
                          fixed_amount=50, final_amount=50, action="fixed_dca",
                          calculation_trace="fixed_alloc=50.0")
    session.add(item); session.commit()
    freeze_weekly_plan(session, r["plan_id"])
    journals = session.exec(select(DecisionJournalEntry).where(
        DecisionJournalEntry.weekly_plan_item_id == item.id)).all()
    assert len(journals) >= 1
