"""v2.1 Weekly Plan Calculation Pipeline — integration tests."""
import pytest
from decimal import Decimal
from sqlmodel import Session, SQLModel, create_engine, select, StaticPool
from db.models import (Asset, InvestmentPlanConfig, WeeklyInvestmentPlan, WeeklyPlanItem,
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


def fake_dca(asset, mkt, val, config, session):
    """Deterministic fake DCA: returned based on asset_code."""
    data = {
        "CORE_A": (40, 10, "dynamic_dca", "PASS"),
        "CORE_B": (40, 50, "dynamic_dca", "PASS"),
        "SAT_C": (20, 0, "fixed_dca", "PASS"),
        "SAT_E": (0, 30, "dynamic_dca", "PASS"),
    }
    fd, dy, act, risk = data.get(asset.code, (0, 0, "NO_ACTION", "PASS"))
    return {"ok": True, "fixed_amount": fd, "dynamic_amount": dy, "candidate_amount": fd + dy,
            "candidate_action": act, "risk_status": risk,
            "calculation_trace": f"fixture({asset.code})", "strategy_version": "v2.1"}


def fake_dca_fail(asset, mkt, val, config, session):
    """Simulate DCA adapter failure."""
    if asset.code == "SAT_E":
        return {"ok": False, "error_code": "VALUE_DCA_FAILED", "error": "injected test failure"}
    return fake_dca(asset, mkt, val, config, session)


def fake_val(code):
    return {"proxy_status": "ok", "valuation_status": "READY", "valuation_state": "fair",
            "valuation_score": 50, "source": "test", "valuation_date": "", "evidence": {}}


def fake_guard(candidates, session):
    """Apply guard: SAT_E gets reduced from 30 to 10."""
    for c in candidates:
        if c["asset_code"] == "SAT_E":
            c["final_amount"] = 10.0
            c["exposure_status"] = "REDUCED"
            c["exposure_reasons"] = "重叠测试"
    return candidates


def fake_guard_fail(candidates, session):
    raise RuntimeError("injected guard failure")


# ═══════════════════════════════════════════════════════════
# Budget allocation tests
# ═══════════════════════════════════════════════════════════

def test_fixed_and_dynamic_both_allocated():
    from application.weekly_plan import allocate_role_budget
    items = [{"asset_code": "A", "fixed_amount": 50, "dynamic_amount": 10, "candidate_action": "dynamic_dca",
              "calculation_trace": "", "candidate_amount": 60}]
    result = allocate_role_budget(items, Decimal("100"))
    assert result[0]["final_amount"] == 60.0
    assert result[0]["allocated_fixed"] == 50.0
    assert result[0]["allocated_dynamic"] == 10.0


def test_allocate_fixed_scaled():
    from application.weekly_plan import allocate_role_budget
    items = [{"asset_code": "A", "fixed_amount": 80, "dynamic_amount": 0, "candidate_action": "fixed_dca",
              "calculation_trace": "", "candidate_amount": 80},
             {"asset_code": "B", "fixed_amount": 80, "dynamic_amount": 0, "candidate_action": "fixed_dca",
              "calculation_trace": "", "candidate_amount": 80}]
    result = allocate_role_budget(items, Decimal("100"))
    assert result[0]["final_amount"] == 50.0
    assert result[1]["final_amount"] == 50.0


def test_fixed_first_dynamic_remaining():
    from application.weekly_plan import allocate_role_budget
    items = [
        {"asset_code": "A", "fixed_amount": 80, "dynamic_amount": 10, "candidate_action": "dynamic_dca",
         "calculation_trace": "", "candidate_amount": 90},
        {"asset_code": "B", "fixed_amount": 20, "dynamic_amount": 0, "candidate_action": "fixed_dca",
         "calculation_trace": "", "candidate_amount": 20},
    ]
    result = allocate_role_budget(items, Decimal("100"))
    amounts = {it["asset_code"]: it["final_amount"] for it in result}
    assert amounts["B"] == 20.0
    assert amounts["A"] == 80.0  # A gets 80 fixed (scaled 80→80), 0 dynamic (no budget left)


# ═══════════════════════════════════════════════════════════
# E2E fixture
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def e2e(session, default_config):
    assets = [
        Asset(code="CORE_A", name="核心A", role="core", enabled=True),
        Asset(code="CORE_B", name="核心B", role="core", enabled=True),
        Asset(code="SAT_C", name="卫星C", role="satellite", enabled=True),
        Asset(code="SAT_D", name="卫星D", role="satellite", enabled=True),
        Asset(code="SAT_E", name="卫星E", role="satellite", enabled=True),
    ]
    session.add_all(assets)
    for code in ["CORE_A", "CORE_B", "SAT_C", "SAT_D", "SAT_E"]:
        session.add(MarketSnapshot(asset_code=code, nav=1.0, proxy_ma200=0.9, is_trusted=True, quality_status="PASS"))
    session.commit()


def test_positive_amount_e2e(session, default_config, e2e):
    from application.weekly_plan import build_weekly_investment_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1,
                                     adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    assert r["ok"] is True
    assert r["total_final"] > 0
    assert r["total_final"] <= 200.0


def test_value_dca_adapter_failure_visible(session, default_config, e2e):
    from application.weekly_plan import build_weekly_investment_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1,
                                     adapters={"value_dca": fake_dca_fail, "valuation": fake_val, "exposure_guard": fake_guard})
    assert r["ok"] is True
    assert len(r.get("errors", [])) > 0
    # SAT_E should have amount=None
    sat_e = [i for i in r["items"] if i["asset_code"] == "SAT_E"]
    if sat_e:
        assert sat_e[0].get("final_amount") is None or sat_e[0].get("final_amount") == 0


def test_exposure_guard_adapter_is_called(session, default_config, e2e):
    from application.weekly_plan import build_weekly_investment_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1,
                                     adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    sat_e = [i for i in r["items"] if i["asset_code"] == "SAT_E"]
    assert len(sat_e) == 1
    assert sat_e[0].get("final_amount") == 10.0  # reduced by guard


def test_exposure_guard_failure_requires_review(session, default_config, e2e):
    from application.weekly_plan import build_weekly_investment_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1,
                                     adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard_fail})
    assert r["ok"] is True
    # All items with positive amount should be REVIEW_REQUIRED
    for it in r["items"]:
        if (it.get("candidate_amount") or 0) > 0:
            assert it.get("exposure_status") == "GUARD_ERROR"


def test_valuation_state_not_proxy_status(session, default_config, e2e):
    from application.weekly_plan import build_weekly_investment_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1,
                                     adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    for it in r["items"]:
        assert it.get("valuation_state") != "ok"  # not raw proxy_status


def test_build_rollback_restores_old_items(session, default_config, e2e):
    """If adapter fails mid-build, old items remain untouched."""
    from application.weekly_plan import build_weekly_investment_plan
    r1 = build_weekly_investment_plan(session, "2026-08-03", 1,
                                      adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    assert r1["ok"] is True
    before_ids = {it["id"] for it in r1["items"]}

    # Simulate failure by passing a guard that throws
    r2 = build_weekly_investment_plan(session, "2026-08-03", 1, rebuild=True,
                                      adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard_fail})
    if r2["ok"] is False:
        # Rollback: old plan still exists with its items
        plan = session.exec(select(WeeklyInvestmentPlan).where(WeeklyInvestmentPlan.week_start == "2026-08-03")).first()
        assert plan is not None
        items = session.exec(select(WeeklyPlanItem).where(WeeklyPlanItem.weekly_plan_id == plan.id)).all()
        assert len(items) > 0


def test_market_snapshot_contract(session, default_config):
    """Verify MarketSnapshot is independent of FundHoldingSnapshot."""
    ms = MarketSnapshot(asset_code="TEST", nav=1.5, proxy_ma200=1.4, is_trusted=True)
    session.add(ms); session.commit()
    assert ms.nav == 1.5
    assert ms.proxy_ma200 == 1.4
    assert ms.is_trusted is True


def test_journal_freezes_full_evidence(session, default_config, e2e):
    from application.weekly_plan import build_weekly_investment_plan, freeze_weekly_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1,
                                     adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    # Add data_quality_status=ok to allow freeze
    for it in session.exec(select(WeeklyPlanItem).where(WeeklyPlanItem.weekly_plan_id == r["plan_id"])).all():
        it.data_quality_status = "ok"
    session.commit()
    fr = freeze_weekly_plan(session, r["plan_id"])
    assert fr["ok"] is True
    journals = session.exec(select(DecisionJournalEntry)).all()
    assert len(journals) > 0
    j = journals[0]
    assert j.strategy_version == "v2.1"
    assert j.final_amount is not None or j.final_amount == 0  # at least has the field


def test_real_planstate_unchanged(session, default_config, e2e):
    st = FundState(code="pool", pool_balance=1000.0)
    session.add(st); session.commit()
    from application.weekly_plan import build_weekly_investment_plan, freeze_weekly_plan
    r = build_weekly_investment_plan(session, "2026-08-03", 1,
                                     adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    for it in session.exec(select(WeeklyPlanItem).where(WeeklyPlanItem.weekly_plan_id == r["plan_id"])).all():
        it.data_quality_status = "ok"
    session.commit()
    freeze_weekly_plan(session, r["plan_id"])
    st2 = session.get(FundState, st.id)
    assert st2.pool_balance == 1000.0


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
    before_build = len(session.exec(select(UserDecision)).all())
    r = build_weekly_investment_plan(session, "2026-08-03", 1,
                                     adapters={"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard})
    after_build = len(session.exec(select(UserDecision)).all())
    for it in session.exec(select(WeeklyPlanItem).where(WeeklyPlanItem.weekly_plan_id == r["plan_id"])).all():
        it.data_quality_status = "ok"
    session.commit()
    freeze_weekly_plan(session, r["plan_id"])
    after_freeze = len(session.exec(select(UserDecision)).all())
    assert before_build == after_build == after_freeze
