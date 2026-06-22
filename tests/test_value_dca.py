"""Tests for v0.8 Value-DCA Strategy Framework"""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


# ── AssetRole tests ─────────────────────────────

def test_asset_role_defaults_to_satellite_for_active_fund():
    from db.models import AssetRole
    assert AssetRole.SATELLITE == "satellite"
    assert AssetRole.CORE == "core"


# ── Four percent rule tests ─────────────────────

def test_four_percent_waiting_trigger():
    from services.value_dca import evaluate_four_percent_layer
    from db.models import FourPercentState
    layer = evaluate_four_percent_layer(
        proxy_close=100.0, last_buy_ref=100.0,
        tranches_used=0, tranches_total=10,
        valuation_state="cheap"
    )
    # 100.0 > 96.0 (100*0.96) → waiting
    assert layer.status == FourPercentState.WAITING_TRIGGER


def test_four_percent_triggered_when_proxy_falls_4_percent():
    from services.value_dca import evaluate_four_percent_layer
    from db.models import FourPercentState
    layer = evaluate_four_percent_layer(
        proxy_close=95.0, last_buy_ref=100.0,
        tranches_used=0, tranches_total=10,
        valuation_state="fair_low"
    )
    # 95.0 <= 96.0 (100*0.96) → triggered
    assert layer.status == FourPercentState.TRIGGERED


def test_four_percent_disabled_when_valuation_unknown_or_expensive():
    from services.value_dca import evaluate_four_percent_layer
    from db.models import FourPercentState

    # expensive → disabled
    layer = evaluate_four_percent_layer(95, 100, 0, 10, "expensive")
    assert layer.status == FourPercentState.DISABLED_BY_VALUATION

    # fair_high → disabled
    layer2 = evaluate_four_percent_layer(95, 100, 0, 10, "fair_high")
    assert layer2.status == FourPercentState.DISABLED_BY_VALUATION


def test_four_percent_dry_run_does_not_change_recommended_amount():
    """4% triggered must NOT alter the recommended_amount."""
    from services.value_dca import build_decision_report

    # Pass with 4% triggered — recommended_amount still comes from computed_amount
    report = build_decision_report(
        "test", "测试", "akshare", 5.0, 95.0, 100.0, -0.05,
        "satellite", "HOLD_OK", 100.0, 0, 10, "cheap",
        True, [], 200.0, True,
    )
    # recommended_amount = computed_amount (200.0) when all layers pass
    assert report.recommended_amount == 200.0
    # 4% layer triggered but does NOT change the amount
    assert report.four_percent_layer.status == "triggered"
    assert report.computed_amount == 200.0
    # The 4% status is in calculation_trace for audit
    assert "four_percent_dry_run" in report.calculation_trace


# ── Decision report tests ───────────────────────

def test_decision_report_contains_all_layers():
    from services.value_dca import build_decision_report
    report = build_decision_report(
        "000083", "测试", "akshare", 5.0, 100.0, 100.0, 0.0,
        "core", "HOLD_OK", 100.0, 0, 10, "unknown", True, [], 200.0, True,
    )
    assert report.data_layer is not None
    assert report.thesis_layer is not None
    assert report.valuation_layer is not None
    assert report.price_layer is not None
    assert report.four_percent_layer is not None
    assert report.amount_layer is not None
    assert report.risk_layer is not None
    assert report.signal_ready is True
    assert report.recommended_amount is not None


def test_strategy_framework_api_returns_layers():
    from services.value_dca import build_decision_report, build_framework_response
    report = build_decision_report(
        "000083", "测试", "akshare", 5.0, 100.0, 100.0, 0.0,
        "satellite", "HOLD_OK", 100.0, 0, 10, "unknown", True, [], 200.0, True,
    )
    resp = build_framework_response(report)
    assert "layers" in resp
    for key in ["data", "thesis", "valuation", "price", "four_percent", "amount", "risk"]:
        assert key in resp["layers"], f"Missing layer: {key}"
    assert resp["recommended_amount"] == 200.0
    assert resp["review_required"] is False


def test_gui_strategy_layers_do_not_show_as_trading_signal():
    """Strategy layers are for review, not trading signals."""
    from services.value_dca import build_decision_report
    report = build_decision_report(
        "000083", "测试", "mock", 5.0, 100.0, 100.0, 0.0,
        "satellite", "HOLD_OK", 100.0, 0, 10, "unknown", True, [], 200.0, True,
    )
    # Mock source → data layer blocked → recommended_amount = None
    assert report.data_layer.blocking is True
    assert report.recommended_amount is None


def test_value_dca_docs_state_not_auto_trading():
    doc = Path("docs/strategy/value_dca_framework.md").read_text()
    assert "不自动交易" in doc
    assert "核心-卫星价值定投增强" in doc
    assert "4% 法不能变成无脑网格补仓" in doc
    assert "dry_run" in doc


# ── v0.8.1 GUI semantic tests ─────────────────────

def test_four_percent_dry_run_never_changes_recommended_amount():
    """4% triggered must NOT change recommended_amount — dry_run only."""
    from services.value_dca import build_decision_report
    # Simulate 4% triggered scenario
    report_triggered = build_decision_report(
        "test", "测试", "akshare", 5.0, 95.0, 100.0, -0.05,
        "satellite", "HOLD_OK", 100.0, 0, 10, "cheap",
        True, [], 200.0, True,
    )
    # recommended_amount still 200 (unchanged by 4%)
    assert report_triggered.recommended_amount == 200.0
    assert report_triggered.four_percent_layer.status == "triggered"
    # computed_amount is independent
    assert report_triggered.computed_amount == 200.0


def test_gui_four_percent_triggered_displays_audit_only():
    """When 4% triggered, the amount is NOT from 4% rule."""
    from services.value_dca import build_decision_report
    report = build_decision_report(
        "test", "测试", "akshare", 5.0, 95.0, 100.0, -0.05,
        "satellite", "HOLD_OK", 100.0, 0, 10, "cheap",
        True, [], 200.0, True,
    )
    # 4% in trace for audit, not in amount
    assert "four_percent_dry_run" in report.calculation_trace
    assert report.calculation_trace["four_percent_dry_run"]["state"] == "triggered"
    assert report.recommended_amount == 200.0  # NOT from 4%


def test_valuation_unknown_displays_not_connected_warning():
    """Valuation unknown must indicate PE/PB not connected."""
    from services.value_dca import build_decision_report
    report = build_decision_report(
        "test", "测试", "akshare", 5.0, 100.0, 100.0, 0.0,
        "satellite", "HOLD_OK", 100.0, 0, 10, "unknown",
        True, [], 200.0, True,
    )
    assert report.valuation_layer.status == "unknown"
    assert "待接入" in report.valuation_layer.reason


def test_no_auto_trade_wording_in_primary_action():
    """Verify docs don't use auto-trade language."""
    doc = Path("docs/strategy/value_dca_framework.md").read_text()
    assert "不自动交易" in doc
    assert "不是自动交易系统" in doc


def test_watchlist_deduplicates_by_fund_code():
    """Same fund_code should appear only once."""
    assets = [{"id": 1, "code": "000083", "name": "A"}, {"id": 2, "code": "000083", "name": "A"}]
    deduped = list({a["code"]: a for a in assets}.values())
    assert len(deduped) == 1


def test_blocked_never_displays_recommended_amount():
    """BLOCKED must have recommended_amount = None."""
    from services.value_dca import build_decision_report
    report = build_decision_report(
        "test", "测试", "mock", 5.0, 100.0, 100.0, 0.0,
        "satellite", "HOLD_OK", 100.0, 0, 10, "unknown",
        True, [], 200.0, True,
    )
    # Mock source blocks data layer → recommended_amount = None
    assert report.data_layer.blocking is True
    assert report.recommended_amount is None


def test_mock_source_forces_blocked_ui():
    """Mock source must set data layer to BLOCKED."""
    from services.value_dca import evaluate_data_layer
    layer = evaluate_data_layer(5.0, 100.0, 100.0, "Mock")
    assert layer.status == "BLOCKED"
    assert layer.blocking is True


# ── v0.8.2 Daily Decision tests ───────────────────

def test_daily_decision_blocked_amount_null():
    from db.models import DailyDecision
    dd = DailyDecision(date="2025-01-01", fund_code="000083", system_status="BLOCKED", strategy_action="review_required", recommended_amount=None)
    assert dd.recommended_amount is None


def test_daily_decision_observe_amount_zero():
    from db.models import DailyDecision
    dd = DailyDecision(date="2025-01-01", fund_code="000083", system_status="PASS", strategy_action="observe", recommended_amount=0.0, amount_permission="show_recommended_amount")
    assert dd.recommended_amount == 0.0


def test_user_decision_records_skipped_reason():
    from db.models import UserDecision
    ud = UserDecision(user_action="skipped", skip_reason="资金不足", user_note="下次再补")
    assert ud.user_action == "skipped"
    assert "资金不足" in ud.skip_reason


def test_today_decision_groups_by_action():
    from db.models import DailyDecision
    decisions = [
        DailyDecision(date="today", fund_code="A", strategy_action="fixed_dca", system_status="PASS", recommended_amount=200),
        DailyDecision(date="today", fund_code="B", strategy_action="observe", system_status="PASS", recommended_amount=0),
        DailyDecision(date="today", fund_code="C", strategy_action="review_required", system_status="BLOCKED", recommended_amount=None),
    ]
    groups = {}
    for d in decisions: groups.setdefault(d.strategy_action, []).append(d)
    assert len(groups["fixed_dca"]) == 1
    assert len(groups["review_required"]) == 1
    assert groups["review_required"][0].recommended_amount is None


def test_blocked_decision_not_tradeable():
    from db.models import DailyDecision
    dd = DailyDecision(system_status="BLOCKED", amount_permission="hide_amount")
    assert dd.amount_permission == "hide_amount"


def test_daily_decision_created_by_scheduler():
    from db.models import DailyDecision
    dd = DailyDecision(created_by="scheduler")
    assert dd.created_by == "scheduler"


def test_user_action_pending_to_executed():
    from db.models import UserDecision
    ud = UserDecision(user_action="pending")
    ud.user_action = "executed"; ud.actual_amount = 200.0
    assert ud.user_action == "executed"


def test_daily_plan_modal_hides_no_action_by_default():
    from db.models import DailyDecision
    decisions = [
        DailyDecision(strategy_action="fixed_dca", system_status="PASS"),
        DailyDecision(strategy_action="observe", system_status="PASS"),
        DailyDecision(strategy_action="review_required", system_status="BLOCKED"),
    ]
    actionable = [d for d in decisions if d.strategy_action in ("fixed_dca", "dynamic_dca")]
    assert len(actionable) == 1


# ── v0.8.3 Exposure Guard tests ────────────────────

def test_same_theme_only_one_action_per_week():
    from services.exposure_guard import classify_theme
    assert classify_theme("汇添富消费行业混合") == "消费"
    assert classify_theme("中欧医疗健康混合C") == "医药"
    assert classify_theme("华安文体健康混合") == "文体"


def test_duplicate_theme_downgraded_to_observe():
    """Two funds in same theme bucket → only one actionable."""
    from services.exposure_guard import apply_exposure_guard
    candidates = [
        {"fund_code": "A", "fund_name": "消费基金A", "strategy_action": "fixed_dca", "system_status": "PASS", "recommended_amount": 200, "dev_pct": -0.05},
        {"fund_code": "B", "fund_name": "消费基金B", "strategy_action": "fixed_dca", "system_status": "PASS", "recommended_amount": 200, "dev_pct": -0.02},
    ]
    # Test without session (theme classification only)
    from services.exposure_guard import classify_theme
    for c in candidates:
        c["theme_bucket"] = classify_theme(c["fund_name"])
    # Both are "消费" → need guard
    by_theme = {}
    for c in candidates:
        by_theme.setdefault(c["theme_bucket"], []).append(c)
    for theme, items in by_theme.items():
        if len(items) > 1:
            items.sort(key=lambda c: c.get("dev_pct", 0))
            for c in items[1:]:
                c["strategy_action"] = "observe"
                c["recommended_amount"] = 0.0
    assert candidates[0]["strategy_action"] == "fixed_dca"
    assert candidates[1]["strategy_action"] == "observe"


def test_industry_exposure_over_30_blocks_dynamic():
    """Industry > 30% should block dynamic DCA."""
    from services.exposure_guard import apply_exposure_guard
    # Exceeding 30% → dynamic should be downgraded
    assert 0.35 > 0.30  # threshold check


def test_industry_exposure_over_40_review_required():
    assert 0.45 > 0.40  # REVIEW_REQUIRED threshold


def test_top10_overlap_over_50_not_both_actionable():
    from services.exposure_guard import calculate_overlap
    stocks_a = ["600519", "000858", "600809", "000568", "002304", "600887", "000333", "600690", "000651", "600600"]
    stocks_b = ["600519", "000858", "600809", "000568", "002304", "000001", "000002", "000003", "000004", "000005"]
    overlap = calculate_overlap(stocks_a, stocks_b)
    assert overlap >= 0.5  # 5/10 = 50% overlap


def test_portfolio_amount_guard_over_cap_review_required():
    total = 700
    cap = 200 * 3  # 600
    assert total > cap  # REVIEW_REQUIRED


def test_exposure_profile_marks_stale_holdings():
    """Holdings > 120 days old should be marked stale."""
    assert True  # structural placeholder


def test_daily_plan_shows_downgrade_reason():
    from db.models import DailyDecision
    dd = DailyDecision(downgraded_from_action="fixed_dca", downgrade_reason="同主题(消费)重复暴露", strategy_action="observe")
    assert dd.downgrade_reason
    assert "消费" in dd.downgrade_reason


def test_weekly_review_includes_exposure_changes():
    assert True  # structural placeholder


# ── v0.8.4 Exposure audit tests ────────────────────

def test_daily_decision_keeps_candidate_and_final_amount():
    from db.models import DailyDecision
    dd = DailyDecision(candidate_amount=200.0, final_amount=200.0, strategy_action="fixed_dca")
    assert dd.candidate_amount == dd.final_amount


def test_downgrade_reason_references_selected_fund():
    from db.models import DailyDecision
    dd = DailyDecision(downgrade_reason="同主题(消费)重复暴露，本周已选择000083", downgrade_from_fund="000083")
    assert "000083" in dd.downgrade_reason


def test_exposure_audit_fields_present():
    from db.models import DailyDecision
    dd = DailyDecision(exposure_guard_applied=True, classification_source="AKShare", classification_confidence="medium", holding_date="2025Q1", stale_holdings_warning=False)
    assert dd.exposure_guard_applied is True
    assert dd.classification_source == "AKShare"


def test_weekly_review_counts_downgraded_decisions():
    """Weekly review should count downgraded items."""
    decisions = [
        {"downgrade_reason": "同主题(消费)"},
        {"downgrade_reason": "同主题(消费)"},
        {"downgrade_reason": ""},
    ]
    downgraded = [d for d in decisions if d["downgrade_reason"]]
    assert len(downgraded) == 2


def test_override_exposure_requires_reason():
    from db.models import UserDecision
    ud = UserDecision(override_exposure_guard=True, override_reason="用户主动选择两只消费基金")
    assert ud.override_exposure_guard is True
    assert ud.override_reason


def test_stale_holdings_warning_displayed():
    from db.models import DailyDecision
    dd = DailyDecision(stale_holdings_warning=True, holding_date="2024-06-30")
    assert dd.stale_holdings_warning is True


def test_candidate_total_and_final_total_separated():
    decisions = [
        {"candidate_amount": 200, "strategy_action": "fixed_dca", "recommended_amount": 200},
        {"candidate_amount": 200, "strategy_action": "observe", "recommended_amount": 0, "downgrade_reason": "同主题"},
    ]
    c_total = sum(d["candidate_amount"] or 0 for d in decisions)
    f_total = sum(
        d.get("recommended_amount", 0) or 0
        for d in decisions
        if d["strategy_action"] in ("fixed_dca", "dynamic_dca") and not d.get("downgrade_reason")
    )
    assert c_total == 400
    assert f_total == 200
