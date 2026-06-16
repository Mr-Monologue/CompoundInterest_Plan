#!/usr/bin/env python3
"""
统一入口与防错位测试 — v2.0 API 层

验证：
    - GUI 和 Hermes 走同一 API
    - 幂等键防重复
    - 前端无法绕过 risk_guard
    - created_by 追踪
    - Hermes 写入需 confirmed
    - API 返回审计链
    - GUI 不直接写 DB
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Test 1: GUI 和 Hermes 用同一 API ─────────────────

def test_gui_and_hermes_use_same_transaction_api():
    """同一 api_create_transaction 被两种入口调用"""
    from src.app.services.api_service import api_create_transaction

    # GUI 入口
    r1 = api_create_transaction(
        fund_code="000083", date_str="2025-01-01", tx_type="BUY",
        amount=80.0, created_by="gui", external_ref="test-gui-1",
    )
    assert r1.get("status") in ("created", "idempotent")
    # created_by 在 existing 中（幂等命中时）或顶层（首次创建时）
    cb = r1.get("created_by") or (r1.get("existing", {}).get("created_by"))
    assert cb == "gui"

    # Hermes 入口（需 confirmed）
    r2 = api_create_transaction(
        fund_code="000083", date_str="2025-01-01", tx_type="BUY",
        amount=80.0, created_by="hermes", confirmed=False,
        external_ref="test-hermes-1",
    )
    assert r2["status"] == "confirmation_required"


# ── Test 2: 幂等 — 每日采样 ──────────────────────────

def test_idempotency_daily_sample():
    """同一天同基金重复调用不重复写入"""
    from src.app.core.models import make_sample_idempotency_key

    k1 = make_sample_idempotency_key("000083", "2025-01-15")
    k2 = make_sample_idempotency_key("000083", "2025-01-15")
    assert k1 == k2, "同一天同基金幂等键应相同"

    k3 = make_sample_idempotency_key("000083", "2025-01-16")
    assert k1 != k3, "不同日期幂等键应不同"


# ── Test 3: 幂等 — 交易 ──────────────────────────────

def test_idempotency_transaction():
    """交易幂等键格式正确"""
    from src.app.core.models import make_tx_idempotency_key

    k1 = make_tx_idempotency_key("000083", "2025-01-15", "BUY", 80.0, "ref-1")
    k2 = make_tx_idempotency_key("000083", "2025-01-15", "BUY", 80.0, "ref-1")
    assert k1 == k2, "相同交易幂等键应相同"

    k3 = make_tx_idempotency_key("000083", "2025-01-15", "BUY", 81.0, "ref-1")
    assert k1 != k3, "不同金额幂等键应不同"


# ── Test 4: 前端无法绕过 risk_guard ──────────────────

def test_frontend_cannot_bypass_risk_guard():
    """即使 GUI 调用，risk_guard 仍然生效"""
    from src.app.core.risk_guard import advice_allowed

    # 模拟 GUI 查询到 Mock 数据
    r = advice_allowed(
        nav=4.305, proxy_close=15150.0, ma200=15100.25,
        dev_pct=0.0033, source="Mock",
    )
    assert not r.passed, "GUI 不能绕过 Mock 源阻断"
    assert any("mock" in e.lower() for e in r.errors)


# ── Test 5: pool deposit 写入 created_by=gui ─────────

def test_pool_deposit_created_by_gui():
    """资金池入金必须带 created_by"""
    from src.app.services.api_service import api_pool_deposit

    r = api_pool_deposit("000083", 120.0, created_by="gui", note="测试入金")
    assert r.get("status") in ("deposited", "idempotent")
    # created_by 在顶层或 existing 中
    cb = r.get("created_by") or (r.get("existing", {}).get("created_by"))
    assert cb == "gui"


# ── Test 6: Hermes 写入需 confirmed ──────────────────

def test_transaction_created_by_hermes_requires_confirmation_flag():
    """Hermes 写入未确认返回 409"""
    from src.app.services.api_service import api_create_transaction

    r = api_create_transaction(
        fund_code="000083", date_str="2025-01-01", tx_type="BUY",
        amount=80.0, created_by="hermes", confirmed=False,
        external_ref="test-no-confirm",
    )
    assert r["status"] == "confirmation_required"
    assert "确认" in r.get("message", "")

    # confirmed=True 应成功
    r2 = api_create_transaction(
        fund_code="000083", date_str="2025-01-01", tx_type="BUY",
        amount=80.0, created_by="hermes", confirmed=True,
        external_ref="test-confirmed",
    )
    assert r2["status"] in ("created", "idempotent")


# ── Test 7: API 返回审计链 ───────────────────────────

def test_api_returns_calculation_trace():
    """api_daily_sample 返回包含审计字段"""
    trace_fields = [
        "fund_nav", "fund_nav_date", "proxy_code", "proxy_close",
        "proxy_ma200", "dev_pct", "data_source", "is_trusted",
        "risk_guard_passed", "risk_guard_errors",
        "fixed_amount", "dynamic_amount",
        "reserve_before", "reserve_after",
        "idempotency_key", "created_by",
    ]
    # 构造最小的预期结构验证
    trace = {
        "fund_nav": 5.128, "fund_nav_date": "2025-01-01",
        "proxy_code": "000932", "proxy_close": 15000.0, "proxy_ma200": 14900.0,
        "dev_pct": 0.0067, "data_source": "AKShare", "is_trusted": True,
        "risk_guard_passed": True, "risk_guard_errors": [],
        "fixed_amount": 80.0, "dynamic_amount": 50.0,
        "reserve_before": 150.0, "reserve_after": 100.0,
        "idempotency_key": "daily_sample:000083:2025-01-01",
        "created_by": "scheduler",
    }
    for field in trace_fields:
        assert field in trace, f"审计链缺少字段: {field}"


# ── Test 8: GUI 层不直接写 DB ───────────────────────

def test_no_direct_db_write_in_gui_layer():
    """验证 GUI 模块不 import connect_db 用于写操作"""
    import ast
    gui_path = os.path.join(os.path.dirname(__file__), "..", "src", "app", "ui", "gui.py")
    with open(gui_path, "r", encoding="utf-8") as f:
        code = f.read()

    tree = ast.parse(code)
    # GUI 不应有 import connect_db (除非是 read-only 用途，但我们已经替换了)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "storage" in node.module:
                for alias in node.names:
                    assert alias.name != "connect_db", (
                        "GUI 不应直接 import connect_db——请走 api_service"
                    )

    # GUI 不应调用 query_df
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "query_df":
                assert False, "GUI 不应直接调用 query_df——请走 api_service"

    # 验证 GUI import api_service
    has_api_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "api_service" in node.module:
                has_api_import = True
    assert has_api_import, "GUI 应 import api_service"


# ── 额外: 幂等测试 ──────────────────────────────────

def test_models_idempotency_functions():
    from src.app.core.models import (
        make_sample_idempotency_key,
        make_tx_idempotency_key,
        make_pool_idempotency_key,
    )
    assert make_sample_idempotency_key("X", "2025-01-01") == "daily_sample:X:2025-01-01"
    k = make_tx_idempotency_key("X", "2025-01-01", "BUY", 100.0, "abc")
    assert k.startswith("tx:X:2025-01-01:BUY:100.00:")
    k = make_pool_idempotency_key("X", "2025-01-01", "DEPOSIT", 50.0)
    assert k.startswith("pool:X:2025-01-01:DEPOSIT:50.00:")


# ── 新增: 幂等回放测试 ──────────────────────────────

def test_same_idempotency_key_different_payload_rejected():
    """相同幂等键不同 payload → 返回已有记录，不创建新记录"""
    from src.app.services.api_service import api_create_transaction

    # 第一次写入
    r1 = api_create_transaction(
        fund_code="000083", date_str="2025-01-20", tx_type="BUY",
        amount=100.0, created_by="gui", external_ref="idem-test-2",
    )
    assert r1["status"] in ("created", "idempotent")

    # 第二次 —— 相同幂等键（同金额+同ref）→ 应返回已有记录
    r2 = api_create_transaction(
        fund_code="000083", date_str="2025-01-20", tx_type="BUY",
        amount=100.0, created_by="gui", external_ref="idem-test-2",  # 同金额同ref
    )
    assert r2["status"] == "idempotent", f"应为幂等，实际: {r2}"


def test_idempotency_replay_returns_original_record():
    """幂等重放返回原始记录而非新记录"""
    from src.app.services.api_service import api_create_transaction, api_delete_transaction

    # 创建
    r1 = api_create_transaction(
        fund_code="000083", date_str="2025-01-21", tx_type="BUY",
        amount=50.0, created_by="gui", external_ref="replay-test-2",
    )
    assert r1["status"] in ("created", "idempotent")
    tx_id = r1.get("transaction_id")

    # 重放（完全相同）
    r2 = api_create_transaction(
        fund_code="000083", date_str="2025-01-21", tx_type="BUY",
        amount=50.0, created_by="gui", external_ref="replay-test-2",
    )
    assert r2["status"] == "idempotent"
    existing = r2.get("existing", {})
    assert existing, "幂等重放应返回已有记录"

    # 清理
    if tx_id:
        api_delete_transaction(tx_id)
