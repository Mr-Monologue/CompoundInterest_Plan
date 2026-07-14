"""v2.1 Weekly Review — real tests."""
import pytest
from sqlmodel import Session, SQLModel, create_engine, select, StaticPool
from db.models import (Asset, InvestmentPlanConfig, WeeklyInvestmentPlan, WeeklyPlanItem, Transaction)
from application.models_reconciliation import (PlanItemUserDecision, ExecutionRecord, ReconciliationRecord)
from application.models_review import WeeklyReview, WeeklyReviewItem, FollowUpAction


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def review_ready_plan(session):
    cfg = InvestmentPlanConfig(id=1, weekly_budget=200, strategy_version="v2.1")
    session.add(cfg)
    a = Asset(code="TEST", name="Test", role="core", enabled=True)
    session.add(a)
    plan = WeeklyInvestmentPlan(week_start="2026-08-03", week_end="2026-08-09", config_id=1,
                                strategy_version="v2.1", status="DRAFT")
    session.add(plan); session.flush()
    item = WeeklyPlanItem(weekly_plan_id=plan.id, asset_code="TEST", action="dynamic_dca",
                          final_amount=100.0, data_quality_status="PASS")
    session.add(item); session.flush()
    plan.status = "FROZEN"
    session.commit()
    dec = PlanItemUserDecision(weekly_plan_item_id=item.id, user_action="APPROVED", approved_amount=80)
    session.add(dec); session.commit()
    er = ExecutionRecord(weekly_plan_item_id=item.id, execution_status="EXECUTED", actual_amount=80,
                         actual_price=1.5, actual_units=53.33, platform="ant",
                         external_reference="TXN001", user_decision_id=dec.id)
    session.add(er); session.commit()
    rec = ReconciliationRecord(execution_record_id=er.id, reconciliation_status="MATCHED",
                               planned_amount=100, approved_amount=80, actual_amount=80,
                               amount_variance=-20)
    session.add(rec); session.flush()
    txn = Transaction(asset_code="TEST", type="BUY", price=1.5, amount=80, fee=0, units=53.33,
                      source_execution_id=er.id)
    session.add(txn); session.commit()
    return plan, item


def test_generate_review_item_count(session, review_ready_plan):
    from application.weekly_review import generate_weekly_review
    plan, _ = review_ready_plan
    r = generate_weekly_review(session, plan.id)
    assert r["ok"] is True
    assert r["review"]["item_count"] == 1


def test_review_category_category(session, review_ready_plan):
    from application.weekly_review import generate_weekly_review
    plan, _ = review_ready_plan
    r = generate_weekly_review(session, plan.id)
    item = r["items"][0]
    assert item["review_category"] == "EXECUTED_MATCHED"


def test_approved_not_executed_incomplete(session, review_ready_plan):
    """Item approved but not yet executed → INCOMPLETE."""
    plan, _ = review_ready_plan
    session.exec(session.execute(select(ExecutionRecord))).first().execution_status = "PENDING"
    session.commit()
    from application.weekly_review import generate_weekly_review
    r = generate_weekly_review(session, plan.id)
    assert r["status"] == "INCOMPLETE"


def test_exact_figures(session, review_ready_plan):
    from application.weekly_review import generate_weekly_review
    plan, _ = review_ready_plan
    r = generate_weekly_review(session, plan.id)
    assert r["review"]["planned_total"] == 100.0
    assert r["review"]["approved_total"] == 80.0
    assert r["review"]["actual_total"] == 80.0
    assert r["review"]["approval_variance_total"] == -20.0
    assert r["review"]["execution_variance_total"] == 0.0


def test_no_none_mistake(session, review_ready_plan):
    """None vs 0 must not be confused."""
    from application.weekly_review import generate_weekly_review
    plan, _ = review_ready_plan
    # Remove transaction, clear execution
    session.exec(session.execute(select(Transaction))).first().delete()
    session.exec(session.execute(select(ReconciliationRecord))).first().delete()
    session.commit()
    r = generate_weekly_review(session, plan.id)
    item = r["items"][0]
    assert item["execution_variance"] is None  # no reconciliation data
    assert item["approval_variance"] == -20.0


def test_closed_cannot_rebuild(session, review_ready_plan):
    from application.weekly_review import generate_weekly_review
    plan, _ = review_ready_plan
    r = generate_weekly_review(session, plan.id)
    rev = session.get(WeeklyReview, r["review_id"])
    rev.status = "CLOSED"
    session.commit()
    r2 = generate_weekly_review(session, plan.id, rebuild=True)
    assert r2["ok"] is False


def test_rebuild_preserves_user_input(session, review_ready_plan):
    from application.weekly_review import generate_weekly_review
    plan, _ = review_ready_plan
    r = generate_weekly_review(session, plan.id)
    rev = session.get(WeeklyReview, r["review_id"])
    rev.user_overall_note = "custom note"
    session.commit()
    r2 = generate_weekly_review(session, plan.id, rebuild=True)
    assert r2["review"]["user_overall_note"] == "custom note"


def test_rebuild_creates_followup_once(session, review_ready_plan):
    from application.weekly_review import generate_weekly_review
    plan, _ = review_ready_plan
    r1 = generate_weekly_review(session, plan.id)
    fa_before = len(session.exec(select(FollowUpAction).where(
        FollowUpAction.weekly_review_id == r1["review_id"])).all())
    r2 = generate_weekly_review(session, plan.id, rebuild=True)
    fa_after = len(session.exec(select(FollowUpAction).where(
        FollowUpAction.weekly_review_id == r2["review_id"])).all())
    assert fa_before == fa_after
