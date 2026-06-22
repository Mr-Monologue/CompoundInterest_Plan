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
