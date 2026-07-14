import sys; sys.path.insert(0, 'backend')
"""v2.1 Product Core Loop E2E — 6 scenario test (fixed)."""
import pytest
from sqlmodel import Session, SQLModel, create_engine, select, StaticPool
from db.models import (Asset, InvestmentPlanConfig, WeeklyInvestmentPlan, WeeklyPlanItem,
                       Transaction, PlanState, MarketSnapshot)
from application.models_reconciliation import (PlanItemUserDecision, ExecutionRecord, ReconciliationRecord)
from application.models_review import WeeklyReview, WeeklyReviewItem, FollowUpAction


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    SQLModel.metadata.drop_all(engine)


def fake_dca(asset, mkt, val, config, session):
    data = {"CORE_A": (40, 0, "fixed_dca"), "CORE_B": (40, 50, "dynamic_dca"),
            "SAT_C": (20, 0, "fixed_dca"), "SAT_E": (0, 20, "dynamic_dca"),
            "SAT_F": (0, 30, "dynamic_dca")}
    fd, dy, act = data.get(asset.code, (0, 0, "NO_ACTION"))
    return {"ok": True, "fixed_amount": fd, "dynamic_amount": dy, "candidate_amount": fd + dy,
            "candidate_action": act, "risk_status": "PASS", "calculation_trace": f"e2e({asset.code})",
            "strategy_version": "v2.1"}


def fake_val(code):
    return {"proxy_status": "ok", "valuation_status": "READY", "valuation_level": "fair",
            "valuation_score": 50, "valuation_date": "2026-08-03", "source": "test", "evidence": {}}


def fake_guard(candidates, session):
    return candidates


def fake_mkt(asset_code):
    from db.models import MarketSnapshot
    return MarketSnapshot(asset_code=asset_code, data_date="2026-08-03", proxy_close=1.05,
                          proxy_ma200=0.9, market_source="test", is_trusted=True, quality_status="PASS")


def setup_e2e(session):
    cfg = InvestmentPlanConfig(id=1, weekly_budget=200, strategy_version="v2.1")
    session.add(cfg)
    codes = {"CORE_A": "core", "CORE_B": "core", "SAT_C": "satellite", "SAT_D": "satellite",
             "SAT_E": "satellite", "SAT_F": "satellite"}
    for code, role in codes.items():
        session.add(Asset(code=code, name=code, role=role, enabled=True, investment_thesis=f"{code} thesis",
                          invalidation_conditions="none"))
        session.add(fake_mkt(code))
    # SAT_D already added above with is_trusted=True — UPDATE it
    mkt_sat_d = session.exec(select(MarketSnapshot).where(
        MarketSnapshot.asset_code == "SAT_D")).first()
    if mkt_sat_d:
        mkt_sat_d.is_trusted = False
        mkt_sat_d.quality_status = "SOURCE_ERROR"
    session.commit()
    from application.weekly_plan import build_weekly_investment_plan
    adapters = {"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard}
    r = build_weekly_investment_plan(session, "2026-08-03", 1, adapters=adapters)
    assert r["ok"] is True
    plan = session.get(WeeklyInvestmentPlan, r["plan_id"])
    items = {i.asset_code: i for i in session.exec(
        select(WeeklyPlanItem).where(WeeklyPlanItem.weekly_plan_id == plan.id)).all()}
    return plan, items


def test_e2e_six_scenarios(session):
    from application.weekly_plan import freeze_weekly_plan
    from application.user_confirmation import submit_decision, submit_execution, reconcile_execution
    from application.weekly_review import generate_weekly_review, submit_user_review, update_follow_up, close_weekly_review

    plan, items = setup_e2e(session)
    freeze_weekly_plan(session, plan.id)

    pool_before = PlanState(id=1, pool_balance=1000.0)
    session.add(pool_before); session.commit()

    # CORE_A: approved=final, actual=final, confirm → MATCHED
    ca = items["CORE_A"]
    submit_decision(session, ca.id, {"user_action": "APPROVED", "approved_amount": ca.final_amount})
    assert ca.final_amount and ca.final_amount > 0
    submit_execution(session, ca.id, {"execution_status": "EXECUTED", "actual_amount": ca.final_amount,
                                       "actual_price": 1.5, "actual_units": ca.final_amount / 1.5,
                                       "platform": "ant", "external_reference": "TXN_CORE_A",
                                       "executed_at": "2026-08-04T10:00:00"})
    reconcile_execution(session, session.exec(select(ExecutionRecord).where(
        ExecutionRecord.weekly_plan_item_id == ca.id)).first().id, {"confirm": True})

    # CORE_B: approved=80% final, confirm → MATCHED
    cb = items["CORE_B"]
    approved_b = round(cb.final_amount * 0.8, 2) if cb.final_amount else 40
    submit_decision(session, cb.id, {"user_action": "APPROVED", "approved_amount": approved_b})
    submit_execution(session, cb.id, {"execution_status": "EXECUTED", "actual_amount": approved_b,
                                       "actual_price": 1.5, "actual_units": approved_b / 1.5,
                                       "platform": "ant", "external_reference": "TXN_CORE_B",
                                       "executed_at": "2026-08-04T10:00:00"})
    reconcile_execution(session, session.exec(select(ExecutionRecord).where(
        ExecutionRecord.weekly_plan_item_id == cb.id)).first().id, {"confirm": True})

    # SAT_C: SKIPPED with reason
    submit_decision(session, items["SAT_C"].id, {"user_action": "SKIPPED", "reason": "卫星仓位已够"})

    # SAT_D: SOURCE_ERROR → BLOCKED, cannot approve
    r = submit_decision(session, items["SAT_D"].id, {"user_action": "APPROVED"})
    assert r["ok"] is False  # must reject

    # SAT_E: DEFERRED
    submit_decision(session, items["SAT_E"].id, {"user_action": "DEFERRED"})

    # SAT_F: approved=30, actual=28, no confirm → MISMATCH
    submit_decision(session, items["SAT_F"].id, {"user_action": "APPROVED", "approved_amount": 30})
    submit_execution(session, items["SAT_F"].id, {"execution_status": "EXECUTED", "actual_amount": 28,
                                                    "actual_price": 1.5, "actual_units": 28 / 1.5,
                                                    "platform": "ant", "external_reference": "TXN_SAT_F",
                                                    "executed_at": "2026-08-04T10:00:00"})
    reconcile_execution(session, session.exec(select(ExecutionRecord).where(
        ExecutionRecord.weekly_plan_item_id == items["SAT_F"].id)).first().id, {"confirm": False})

    # Generate review once
    r = generate_weekly_review(session, plan.id)
    assert r["ok"] is True
    review_id = r["review_id"]

    # Verify categories
    rev_items = {ri["asset_code"]: ri for ri in r["items"]}
    assert rev_items["CORE_A"]["review_category"] == "EXECUTED_MATCHED"
    assert rev_items["SAT_C"]["review_category"] == "SKIPPED"
    assert rev_items["SAT_E"]["review_category"] == "DEFERRED"
    assert rev_items["SAT_F"]["review_category"] == "EXECUTED_MISMATCH"

    # User review
    submit_user_review(session, review_id, {"overall_note": "e2e done", "item_variance_reasons": {},
                                              "confirm": True})

    # Complete follow-ups
    for fa in session.exec(select(FollowUpAction).where(
        FollowUpAction.weekly_review_id == review_id, FollowUpAction.status == "OPEN")).all():
        update_follow_up(session, fa.id, {"status": "DONE", "verification_result": "resolved"})

    # Close
    close_weekly_review(session, review_id, {"confirm_close": True})

    # Verify safety
    pool_after = session.get(PlanState, pool_before.id)
    assert pool_after is not None
    assert pool_after.pool_balance == 1000.0

    # Verify transactions
    txns = session.exec(select(Transaction)).all()
    assert len(txns) == 2  # CORE_A + CORE_B only
    for t in txns:
        assert t.type == "BUY"
        assert t.source_execution_id is not None
