"""Tests for Hermes Runtime Adapter — Phase 2"""
import sys
import os
from pathlib import Path
from datetime import date
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, ".")


# ── Test 1: Tool Registry loads tools ────────────────

def test_tool_registry_loads_tools():
    from hermes.runtime.tool_registry import load_registry, get_tool, list_tools

    reg = load_registry()
    names = list_tools()
    assert len(names) >= 10, f"Expected >=10 tools, got {len(names)}"

    health = get_tool("health_check")
    assert health["method"] == "GET"
    assert not health["requires_token"]
    assert not health["writes_db"]

    daily = get_tool("daily_sample")
    assert daily["method"] == "POST"
    assert daily["requires_token"]
    assert daily["writes_db"]


# ── Test 2: Unknown tool rejected ────────────────────

def test_unknown_tool_rejected():
    from hermes.runtime.tool_registry import get_tool

    with pytest.raises(KeyError) as exc:
        get_tool("nonexistent_tool")
    assert "nonexistent_tool" in str(exc.value)
    assert "Available:" in str(exc.value)


# ── Test 3: Token required blocks without token ──────

def test_requires_token_blocks_without_token(monkeypatch):
    from hermes.runtime import config

    # Simulate no token
    monkeypatch.setattr(config, "_LOCAL_TOKEN", "")
    assert not config.has_token()

    with pytest.raises(RuntimeError) as exc:
        config.require_token()
    assert "CIP_API_TOKEN" in str(exc.value)


# ── Test 4: BLOCKED result hides recommended_amount ──

def test_blocked_result_hides_recommended_amount():
    from hermes.runtime.policy_checker import check_policy

    r = check_policy({
        "action_allowed": False,
        "recommended_amount": None,
        "data_source": "Mock",
        "is_trusted": False,
        "risk_guard_passed": False,
    })
    assert r["status"] == "BLOCKED"
    assert not r["safe_to_display_amount"]
    assert r["recommended_amount"] is None
    assert len(r["errors"]) >= 1


# ── Test 5: computed_amount only in audit ─────────────

def test_computed_amount_only_audit():
    from hermes.runtime.report_writer import write_blocked_alert
    from pathlib import Path
    import tempfile

    policy = {
        "status": "BLOCKED",
        "safe_to_display_amount": False,
        "recommended_amount": None,
        "errors": ["source is Mock"],
    }
    result = {
        "fund_code": "000083",
        "data_source": "Mock",
        "is_trusted": False,
        "risk_guard_passed": False,
        "action_allowed": False,
        "calculation_trace": {
            "computed_amount": 192.50,
            "fixed_amount": 80.00,
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        p = write_blocked_alert(Path(tmp), result, policy, date(2025, 1, 15))
        content = p.read_text()
        assert "null" in content
        assert "192.50" not in content, "computed_amount should not appear in BLOCKED alert"
        assert "不输出买入金额" in content


# ── Test 6: action_allowed=false with amount → P0 ────

def test_action_allowed_false_with_amount_is_p0_anomaly():
    from hermes.runtime.policy_checker import check_policy

    r = check_policy({
        "action_allowed": False,
        "recommended_amount": 192.50,
        "data_source": "AKShare",
        "is_trusted": True,
        "risk_guard_passed": True,
    })
    assert r["status"] == "BLOCKED"
    has_p0 = any("P0" in e for e in r["errors"])
    assert has_p0, f"Expected P0 anomaly, got: {r['errors']}"


# ── Test 7: daily_sample BLOCKED writes alert ─────────

def test_run_once_daily_sample_blocked_writes_alert(monkeypatch, tmp_path):
    from hermes.runtime import config
    from hermes.runtime.report_writer import (
        write_daily_report, write_blocked_alert
    )

    result = {
        "fund_code": "000083",
        "fund_nav": 4.305,
        "fund_nav_date": "2025-01-15",
        "data_source": "Mock",
        "is_trusted": False,
        "risk_guard_passed": False,
        "action_allowed": False,
        "recommended_amount": None,
        "calculation_trace": {"computed_amount": 192.50, "fixed_amount": 80.00},
    }
    policy = {
        "status": "BLOCKED",
        "safe_to_display_amount": False,
        "recommended_amount": None,
        "errors": ["source is Mock", "risk_guard failed"],
    }

    daily = write_daily_report(tmp_path, result, policy, date(2025, 1, 15))
    alert = write_blocked_alert(tmp_path, result, policy, date(2025, 1, 15))

    daily_text = daily.read_text()
    alert_text = alert.read_text()

    assert "BLOCKED" in daily_text
    assert "null" in daily_text
    assert "建议金额: ¥" not in daily_text, "BLOCKED report must not show buy amount"
    assert "BLOCKED" in alert_text
    assert "不输出买入金额" in alert_text


# ── Test 8: confirm_transaction disabled in Phase 2 ──

def test_confirm_transaction_disabled_in_phase2():
    from hermes.runtime.tool_executor import execute_tool, PHASE2_DISABLED

    assert "confirm_transaction" in PHASE2_DISABLED

    with pytest.raises(RuntimeError) as exc:
        execute_tool("confirm_transaction")
    assert "DISABLED" in str(exc.value)
    assert "Phase 2" in str(exc.value)
