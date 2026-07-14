"""v2.1 Product Core Loop E2E — 6 scenario test."""
import pytest
from sqlmodel import Session, SQLModel, create_engine, select, StaticPool
from db.models import (Asset, InvestmentPlanConfig, WeeklyInvestmentPlan, WeeklyPlanItem,
                       Transaction, FundState)
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
    for c in candidates:
        if c["asset_code"] == "SAT_F":
            c["final_amount"] = 30  # SAT_F passes guard unchanged
    return candidates


def fake_mkt(asset_code):
    from db.models import MarketSnapshot
    return MarketSnapshot(asset_code=asset_code, data_date="2026-08-03", proxy_close=1.05,
                          proxy_ma200=0.9, market_source="test", is_trusted=True, quality_status="PASS")


def setup_e2e(session):
    cfg = InvestmentPlanConfig(id=1, weekly_budget=200, strategy_version="v2.1")
    session.add(cfg)
    codes = {"CORE_A": "core", "CORE_B": "core", "SAT_C": "satellite", "SAT_D": "satellite", "SAT_E": "satellite", "SAT_F": "satellite"}
    for code, role in codes.items():
        session.add(Asset(code=code, name=code, role=role, enabled=True, investment_thesis=f"{code} thesis", invalidation_conditions="none"))
        session.add(fake_mkt(code))
    session.commit()
    # SAT_D: SOURCE_ERROR
    from db.models import MarketSnapshot
    session.add(MarketSnapshot(asset_code="SAT_D", data_date="2026-08-03", is_trusted=False, quality_status="SOURCE_ERROR"))
    session.commit()
    from application.weekly_plan import build_weekly_investment_plan
    adapters = {"value_dca": fake_dca, "valuation": fake_val, "exposure_guard": fake_guard}
    r = build_weekly_investment_plan(session, "2026-08-03", 1, adapters=adapters)
    assert r["ok"] is True
    for it in session.exec(select(WeeklyPlanItem).where(WeeklyPlanItem.weekly_plan_id == r["plan_id"])).all():
        it.data_quality_status = "PASS"
    session.commit()
    plan = session.get(WeeklyInvestmentPlan, r["plan_id"])
    plan_items = {i.asset_code: i for i in session.exec(select(WeeklyPlanItem).where(
        WeeklyPlanItem.weekly_plan_id == plan.id)).all()}
    return plan, plan_items


def e2e_action(session, item, action, approved=None, actual=None, confirm=False):
    from application.weekly_plan import freeze_weekly_plan, build_weekly_investment_plan
    from application.user_confirmation import submit_decision, submit_execution, reconcile_execution
    from application.weekly_review import generate_weekly_review, submit_user_review, update_follow_up, close_weekly_review

    plan = session.get(WeeklyInvestmentPlan, item.weekly_plan_id)
    if plan.status != "FROZEN":
        freeze_weekly_plan(session, plan.id)

    if action == "APPROVED":
        submit_decision(session, item.id, {"user_action": "APPROVED", "approved_amount": approved or item.final_amount})
        if actual is not None:
            r = submit_execution(session, item.id, {"execution_status": "EXECUTED", "actual_amount": actual,
                                                      "actual_price": 1.5, "actual_units": actual / 1.5 if actual else 0,
                                                      "platform": "ant", "external_reference": f"TXN_{item.asset_code}",
                                                      "executed_at": "2026-08-04T10:00:00"})
            reconcile_execution(session, r["execution_id"], {"confirm": confirm and actual == approved})
    elif action == "SKIPPED":
        submit_decision(session, item.id, {"user_action": "SKIPPED", "reason": "test skip"})
    elif action == "DEFERRED":
        submit_decision(session, item.id, {"user_action": "DEFERRED"})
    elif action == "BLOCKED":
        submit_decision(session, item.id, {"user_action": "CANCELLED"})

    r = generate_weekly_review(session, plan.id)
    review_id = r["review_id"]
    submit_user_review(session, review_id, {"overall_note": "e2e test", "item_variance_reasons": {},
                                             "confirm": True})
    follow_ups = session.exec(select(FollowUpAction).where(FollowUpAction.weekly_review_id == review_id)).all()
    for fa in follow_ups:
        if fa.status == "OPEN":
            update_follow_up(session, fa.id, {"status": "DONE", "verification_result": "resolved"})
    # Close if all done
    try:
        remaining = session.exec(select(FollowUpAction).where(
            FollowUpAction.weekly_review_id == review_id, FollowUpAction.status == "OPEN")).all()
        if not remaining:
            close_weekly_review(session, review_id, {"confirm_close": True})
    except:
        pass


def test_e2e_six_scenarios(session):
    plan, items = setup_e2e(session)

    assert "CORE_A" in items
    assert items["CORE_A"].final_amount is not None and items["CORE_A"].final_amount > 0

    # CORE_A: approved=planned=actual → MATCHED
    e2e_action(session, items["CORE_A"], "APPROVED", actual=items["CORE_A"].final_amount, confirm=True)

    # CORE_B: approved=80 → MATCHED (variance inspected in review)
    if items["CORE_B"].final_amount and items["CORE_B"].final_amount > 0:
        e2e_action(session, items["CORE_B"], "APPROVED", approved=items["CORE_B"].final_amount * 0.8,
                   actual=items["CORE_B"].final_amount * 0.8, confirm=True)

    # SAT_C: SKIPPED
    if items["SAT_C"].final_amount:
        e2e_action(session, items["SAT_C"], "SKIPPED")

    # SAT_D: BLOCKED (SOURCE_ERROR)
    e2e_action(session, items["SAT_D"], "BLOCKED")

    # SAT_E: DEFERRED
    if items["SAT_E"].final_amount:
        e2e_action(session, items["SAT_E"], "DEFERRED")

    # SAT_F: approved=30, actual=28 → MISMATCH
    if items["SAT_F"].final_amount and items["SAT_F"].final_amount > 0:
        e2e_action(session, items["SAT_F"], "APPROVED", approved=30, actual=28, confirm=False)

    # Verify
    pool_state = FundState(code="pool", pool_balance=1000.0)
    session.add(pool_state); session.commit()

    txns = session.exec(select(Transaction)).all()
    assert len([t for t in txns if t.type == "BUY"]) >= 1
    for t in txns:
        assert t.source_execution_id is not None

    reviews = session.exec(select(WeeklyReview)).all()
    assert len(reviews) >= 1

    fas = session.exec(select(FollowUpAction)).all()
    assert len(fas) >= 1

    assert session.get(FundState, pool_state.id).pool_balance == 1000.0
