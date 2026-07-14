"""v2.1 Weekly Plan — production tests."""
import pytest
from decimal import Decimal
from sqlmodel import Session, SQLModel, create_engine, select, StaticPool
from db.models import (Asset, InvestmentPlanConfig, PlanState, WeeklyInvestmentPlan, WeeklyPlanItem,
                       DecisionJournalEntry, DailyDecision, Transaction, FundState,
                       FundHoldingSnapshot, MarketSnapshot)


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


def test_weekly_plan_module_imports():
    from application import weekly_plan
    assert weekly_plan.build_weekly_investment_plan
    from application.adapters.value_dca_adapter import calculate_asset_candidate
    from application.adapters.valuation_adapter import get_valuation_state
    from application.adapters.exposure_guard_adapter import apply_exposure_guard_batch
    assert calculate_asset_candidate
    assert get_valuation_state
    assert apply_exposure_guard_batch


# ── Budget tests ──

def test_fixed_and_dynamic_both_allocated():
    from application.weekly_plan import allocate_role_budget
    items = [{"asset_code": "A", "fixed_amount": 50, "dynamic_amount": 10, "candidate_action": "dynamic_dca",
              "calculation_trace": "", "candidate_amount": 60}]
    result = allocate_role_budget(items, Decimal("100"))
    assert result[0]["final_amount"] == 60.0
    assert result[0]["allocated_fixed"] == 50.0
    assert result[0]["allocated_dynamic"] == 10.0


# ── E2E fixtures ──

@pytest.fixture
def e2e(session, default_config):
    for code, role in [("CORE_A", "core"), ("CORE_B", "core"), ("SAT_C", "satellite"), ("SAT_D", "satellite"), ("SAT_E", "satellite")]:
        session.add(Asset(code=code, name=code, role=role, enabled=True))
    for code in ["CORE_A", "CORE_B", "SAT_C", "SAT_D", "SAT_E"]:
        session.add(MarketSnapshot(asset_code=code, data_date="2026-08-03", nav=1.0, proxy_close=1.1,
                                   proxy_ma200=0.9, market_source="test", is_trusted=True, quality_status="PASS"))
    session.commit()


def fake_dca(asset, mkt, val, config, session):
    data = {"CORE_A": (40, 10, "dynamic_dca"), "CORE_B": (40, 50, "dynamic_dca"),
            "SAT_C": (20, 0, "fixed_dca"), "SAT_E": (0, 30, "dynamic_dca")}
    fd, dy, act = data.get(asset.code, (0, 0, "NO_ACTION"))
    return {"ok": True, "fixed_amount": fd, "dynamic_amount": dy, "candidate_amount": fd + dy,
            "candidate_action": act, "risk_status": "PASS",
            "calculation_trace": f"fixture({asset.code})", "strategy_version": "v2.1"}


def fake_val(code):
    return {"proxy_status": "ok", "valuation_status": "READY", "valuation_level": "fair",
            "valuation_score": 50, "valuation_date": "2026-08-03", "source": "test", "evidence": {}}


def fake_guard(candidates, session):
    for c in candidates:
        if c["asset_code"] == "SAT_E":
            c["final_amount"] = 10.0; c["exposure_status"] = "REDUCED"; c["exposure_reasons"] = "重叠测试"
    return candidates


def fake_guard_fail(candidates, session):
    raise RuntimeError("injected guard failure")


# ── Production adapter tests ──

def test_production_value_dca_uses_proxy_close():
    from application.adapters.value_dca_adapter import calculate_asset_candidate
    from sqlmodel import Session
    mkt = MarketSnapshot(proxy_close=1.1, proxy_ma200=0.9)
    result = calculate_asset_candidate(Asset(code="TEST"), mkt, {}, InvestmentPlanConfig(strategy_version="v2.1"), None)
    assert result["candidate_amount"] > 0


def test_expensive_valuation_has_zero_dynamic():
    from application.adapters.value_dca_adapter import calculate_asset_candidate
    mkt = MarketSnapshot(proxy_close=1.2, proxy_ma200=1.0)
    result = calculate_asset_candidate(Asset(code="TEST"), mkt,
                                       {"valuation_level": "expensive"}, InvestmentPlanConfig(strategy_version="v2.1"), None)
    assert result["dynamic_amount"] == 0


def test_production_valuation_field_mapping():
    from application.adapters.valuation_adapter import get_valuation_state
    result = get_valuation_state("CORE_A")
    assert "valuation_level" in result
    assert "valuation_score" in result
    assert "valuation_date" in result


def test_production_guard_contract():
    """Verify guard adapter input/output mapping."""
    from application.adapters.exposure_guard_adapter import apply_exposure_guard_batch
    from sqlmodel import Session
    candidates = [{"asset_code": "TEST", "asset_role": "core", "candidate_action": "dynamic_dca",
                   "risk_status": "PASS", "candidate_amount": 50, "final_amount": 50}]
    result = apply_exposure_guard_batch(candidates, None)
    assert len(result) == 1
    assert result[0]["exposure_status"] in ("ok", "REDUCED", "BLOCKED", "REVIEW_REQUIRED", "GUARD_ERROR")


# ── Data quality gate tests ──

def test_non_pass_does_not_consume_budget(session, default_config, e2e):
    """REVIEW_REQUIRED/BLOCKED/SOURCE_ERROR assets should not consume budget."""
    from application.weekly_plan import build_weekly_investment_plan
    # Make SAT_D have SOURCE_ERROR
    mkt = session.exec(select(MarketSnapshot).where(MarketSnapshot.asset_code == "SAT_D")).first()
    mkt.is_trusted = False; mkt.quality_status = "SOURCE_ERROR"
    session.commit()
    r = build_weekly_investment_plan(session, "2026-08-03", 1,
                                     adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    assert r["ok"] is True
    sat_d = [i for i in r["items"] if i["asset_code"] == "SAT_D"]
    if sat_d:
        assert sat_d[0].get("final_amount") is None or sat_d[0].get("final_amount") == 0


# ── Transaction rollback tests ──

def test_full_transaction_rollback(session, default_config, e2e):
    from application.weekly_plan import build_weekly_investment_plan
    r1 = build_weekly_investment_plan(session, "2026-08-03", 1,
                                      adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    assert r1["ok"] is True
    old_ids = {it["id"] for it in r1["items"]}
    old_amounts = {it["id"]: it.get("final_amount") for it in r1["items"]}

    r2 = build_weekly_investment_plan(session, "2026-08-03", 1, rebuild=True,
                                      adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard_fail})
    assert r2["ok"] is False
    # Old items must still exist
    new_items = session.exec(select(WeeklyPlanItem).where(
        WeeklyPlanItem.weekly_plan_id == r1["plan_id"])).all()
    new_ids = {it.id for it in new_items}
    assert old_ids == new_ids
    for it in new_items:
        assert it.final_amount == old_amounts.get(it.id)


# ── Journal tests ──

def test_journal_evidence_not_empty(session, default_config, e2e):
    from application.weekly_plan import build_weekly_investment_plan, freeze_weekly_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1,
                                     adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    for it in session.exec(select(WeeklyPlanItem).where(WeeklyPlanItem.weekly_plan_id == r["plan_id"])).all():
        it.data_quality_status = "ok"
    session.commit()
    freeze_weekly_plan(session, r["plan_id"])
    journals = session.exec(select(DecisionJournalEntry)).all()
    assert len(journals) > 0
    j = journals[0]
    assert j.strategy_version == "v2.1"
    assert j.market_data_date is not None
    assert j.data_source is not None
    assert j.proxy_code is not None
    assert j.valuation_state is not None
    assert j.risk_status is not None
    assert j.exposure_status is not None
    assert j.calculation_trace is not None


# ── Safety tests ──

def test_no_transaction_created(session, default_config, e2e):
    from application.weekly_plan import build_weekly_investment_plan
    before = len(session.exec(select(Transaction)).all())
    build_weekly_investment_plan(session, "2026-08-03", 1,
                                 adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    after = len(session.exec(select(Transaction)).all())
    assert after == before


def test_no_userdecision_created(session, default_config, e2e):
    from application.weekly_plan import build_weekly_investment_plan, freeze_weekly_plan
    from db.models import UserDecision
    before = len(session.exec(select(UserDecision)).all())
    r = build_weekly_investment_plan(session, "2026-08-03", 1,
                                     adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    for it in session.exec(select(WeeklyPlanItem).where(WeeklyPlanItem.weekly_plan_id == r["plan_id"])).all():
        it.data_quality_status = "ok"
    session.commit()
    freeze_weekly_plan(session, r["plan_id"])
    assert len(session.exec(select(UserDecision)).all()) == before


def test_pool_balance_unchanged(session, default_config, e2e):
    st = PlanState(id=1, pool_balance=1000.0)
    session.add(st); session.commit()
    from application.weekly_plan import build_weekly_investment_plan, freeze_weekly_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1,
                                     adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    for it in session.exec(select(WeeklyPlanItem).where(WeeklyPlanItem.weekly_plan_id == r["plan_id"])).all():
        it.data_quality_status = "ok"
    session.commit()
    freeze_weekly_plan(session, r["plan_id"])
    assert session.get(PlanState, st.id).pool_balance == 1000.0


# ── Snapshot tests ──

def test_latest_snapshot_before_week_end(session, default_config):
    session.add_all([
        MarketSnapshot(asset_code="TEST", data_date="2026-08-01", is_trusted=True, proxy_close=1.0, proxy_ma200=0.9),
        MarketSnapshot(asset_code="TEST", data_date="2026-08-03", is_trusted=True, proxy_close=1.05, proxy_ma200=0.9),
    ])
    session.add(Asset(code="TEST", role="core", enabled=True))
    session.commit()
    from application.weekly_plan import build_weekly_investment_plan
    r = build_weekly_investment_plan(session, "2026-08-04", 1,
                                     adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    assert r["ok"] is True
    items = [i for i in r["items"] if i["asset_code"] == "TEST"]
    assert len(items) > 0
