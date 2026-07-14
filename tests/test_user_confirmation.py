"""v2.1 User Confirmation — real tests."""
import pytest
from decimal import Decimal
from datetime import datetime
from sqlmodel import Session, SQLModel, create_engine, select, StaticPool
from db.models import (Asset, InvestmentPlanConfig, WeeklyInvestmentPlan, WeeklyPlanItem,
                       Transaction, FundState)
from application.models_reconciliation import (PlanItemUserDecision, ExecutionRecord, ReconciliationRecord)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def frozen_plan(session):
    cfg = InvestmentPlanConfig(id=1, name="default", weekly_budget=200, core_target_ratio=0.65,
                               satellite_target_ratio=0.35, strategy_version="v2.1")
    session.add(cfg)
    a = Asset(code="TEST", name="Test", role="core", enabled=True)
    session.add(a)
    plan = WeeklyInvestmentPlan(week_start="2026-08-03", week_end="2026-08-09", config_id=1,
                                strategy_version="v2.1", status="DRAFT")
    session.add(plan); session.flush()
    item = WeeklyPlanItem(weekly_plan_id=plan.id, asset_code="TEST", action="dynamic_dca",
                          final_amount=100.0, data_quality_status="PASS")
    session.add(item)
    plan.status = "FROZEN"
    session.commit()
    return plan, item


def test_only_frozen_plan_accepts_decision(session, frozen_plan):
    from application.user_confirmation import submit_decision
    plan, item = frozen_plan
    plan.status = "DRAFT"
    session.commit()
    r = submit_decision(session, item.id, {"user_action": "APPROVED", "approved_amount": 50})
    assert r["ok"] is False


def test_blocked_item_cannot_be_approved(session, frozen_plan):
    from application.user_confirmation import submit_decision
    _, item = frozen_plan
    item.action = "BLOCKED"; session.commit()
    r = submit_decision(session, item.id, {"user_action": "APPROVED"})
    assert r["ok"] is False


def test_approved_amount_cannot_exceed_final(session, frozen_plan):
    from application.user_confirmation import submit_decision
    _, item = frozen_plan
    r = submit_decision(session, item.id, {"user_action": "APPROVED", "approved_amount": 999})
    assert r["ok"] is False


def test_skipped_requires_reason(session, frozen_plan):
    from application.user_confirmation import submit_decision
    _, item = frozen_plan
    r = submit_decision(session, item.id, {"user_action": "SKIPPED"})
    assert r["ok"] is False
    r2 = submit_decision(session, item.id, {"user_action": "SKIPPED", "reason": "not now"})
    assert r2["ok"] is True


def test_execution_requires_approved_decision(session, frozen_plan):
    from application.user_confirmation import submit_execution, submit_decision
    _, item = frozen_plan
    r = submit_execution(session, item.id, {"execution_status": "EXECUTED", "actual_amount": 50,
                                             "actual_price": 1.5, "actual_units": 33.33,
                                             "platform": "ant", "external_reference": "TXN001",
                                             "executed_at": "2026-08-04T10:00:00"})
    assert r["ok"] is False
    submit_decision(session, item.id, {"user_action": "APPROVED", "approved_amount": 50})
    r2 = submit_execution(session, item.id, {"execution_status": "EXECUTED", "actual_amount": 50,
                                              "actual_price": 1.5, "actual_units": 33.33,
                                              "platform": "ant", "external_reference": "TXN001",
                                              "executed_at": "2026-08-04T10:00:00"})
    assert r2["ok"] is True


def test_invalid_executed_at_rejected(session, frozen_plan):
    from application.user_confirmation import submit_decision, submit_execution
    _, item = frozen_plan
    submit_decision(session, item.id, {"user_action": "APPROVED", "approved_amount": 50})
    r = submit_execution(session, item.id, {"execution_status": "EXECUTED", "actual_amount": 50,
                                             "actual_price": 1.5, "actual_units": 33,
                                             "platform": "ant", "external_reference": "TXN001",
                                             "executed_at": "not-a-date"})
    assert r["ok"] is False


def test_same_external_ref_same_payload_idempotent(session, frozen_plan):
    from application.user_confirmation import submit_decision, submit_execution
    _, item = frozen_plan
    submit_decision(session, item.id, {"user_action": "APPROVED", "approved_amount": 50})
    data = {"execution_status": "EXECUTED", "actual_amount": 50, "actual_price": 1.5,
            "actual_units": 33, "platform": "ant", "external_reference": "TXN001",
            "executed_at": "2026-08-04T10:00:00"}
    r1 = submit_execution(session, item.id, data)
    r2 = submit_execution(session, item.id, data)
    assert r2["ok"] is True
    assert r2.get("idempotent") is True


def test_same_external_ref_different_payload_conflict(session, frozen_plan):
    from application.user_confirmation import submit_decision, submit_execution
    _, item = frozen_plan
    submit_decision(session, item.id, {"user_action": "APPROVED", "approved_amount": 50})
    r1 = submit_execution(session, item.id, {"execution_status": "EXECUTED", "actual_amount": 50,
                                              "actual_price": 1.5, "actual_units": 33,
                                              "platform": "ant", "external_reference": "TXN001",
                                              "executed_at": "2026-08-04T10:00:00"})
    r2 = submit_execution(session, item.id, {"execution_status": "EXECUTED", "actual_amount": 99,
                                              "actual_price": 1.5, "actual_units": 33,
                                              "platform": "ant", "external_reference": "TXN001",
                                              "executed_at": "2026-08-04T10:00:00"})
    assert r2["ok"] is False
    assert "CONFLICT" in r2.get("error", "")


def test_reconcile_creates_transaction(session, frozen_plan):
    from application.user_confirmation import submit_decision, submit_execution, reconcile_execution
    _, item = frozen_plan
    submit_decision(session, item.id, {"user_action": "APPROVED", "approved_amount": 50})
    r = submit_execution(session, item.id, {"execution_status": "EXECUTED", "actual_amount": 50,
                                             "actual_price": 1.5, "actual_units": 33,
                                             "platform": "ant", "external_reference": "TXN001",
                                             "executed_at": "2026-08-04T10:00:00"})
    rec = reconcile_execution(session, r["execution_id"], {"confirm": True})
    assert rec["ok"] is True
    assert rec["status"] == "MATCHED"
    txn = session.get(Transaction, rec["transaction_id"])
    assert txn is not None
    assert txn.type == "BUY"
    assert txn.source_execution_id == r["execution_id"]


def test_pool_balance_unchanged(session, frozen_plan):
    st = FundState(code="pool", pool_balance=1000.0)
    session.add(st); session.commit()
    from application.user_confirmation import submit_decision, submit_execution, reconcile_execution
    _, item = frozen_plan
    submit_decision(session, item.id, {"user_action": "APPROVED", "approved_amount": 50})
    r = submit_execution(session, item.id, {"execution_status": "EXECUTED", "actual_amount": 50,
                                             "actual_price": 1.5, "actual_units": 33,
                                             "platform": "ant", "external_reference": "TXN001",
                                             "executed_at": "2026-08-04T10:00:00"})
    reconcile_execution(session, r["execution_id"], {"confirm": True})
    assert session.get(FundState, st.id).pool_balance == 1000.0
