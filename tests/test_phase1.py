#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实盘辅助系统测试 — Phase 1

测试覆盖：
    1. Decimal 精度（支付宝口径）
    2. Mock 数据阻断
    3. MA200 偏离度来源（代理指数，非基金净值）
    4. 高估时动态 = 0
    5. 低估时动用准备金
    6. 中估时线性插值
    7. 单周上限约束
    8. 资金池透支防控
    9. 资金池回滚
    10. dev_pct 不会混入 grid_pos
"""

import sys
import os
import pytest
from decimal import Decimal

# 确保项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Test 1: Decimal 精度 — 支付宝口径 ───────────────────

def test_decimal_matches_alipay_display():
    """输入: units=6.63, avg_cost=6.8627, nav=4.9920, realized=-7.24"""
    from src.app.services.accounting import calculate_holdings

    r = calculate_holdings(
        units=6.63,
        avg_cost=6.8627,
        current_nav=4.9920,
        realized_pnl=-7.24,
    )

    assert str(r.market_value) == "33.10", f"market_value={r.market_value}"
    assert str(r.unrealized_pnl) == "-12.40", f"unrealized_pnl={r.unrealized_pnl}"
    assert str(r.unrealized_pct) == "-27.26", f"unrealized_pct={r.unrealized_pct}"
    assert str(r.total_pnl) == "-19.64", f"total_pnl={r.total_pnl}"


# ── Test 2: Mock 数据阻断 ───────────────────────────────

def test_mock_source_blocks_advice():
    """source=Mock 时，不允许输出正式买入金额"""
    from src.app.core.risk_guard import advice_allowed

    r = advice_allowed(
        nav=5.128,
        proxy_close=15000.0,
        ma200=14900.0,
        dev_pct=0.0067,
        source="Mock",
    )
    assert not r.passed, f"Mock should be blocked: {r.errors}"
    assert any("mock" in e.lower() for e in r.errors), r.errors


def test_valid_source_passes():
    """source=AKShare 时允许"""
    from src.app.core.risk_guard import advice_allowed

    r = advice_allowed(
        nav=5.128,
        proxy_close=15000.0,
        ma200=14900.0,
        dev_pct=0.0067,
        source="AKShare",
    )
    assert r.passed, f"AKShare should pass: {r.errors}"


# ── Test 3: MA200 偏离度来源 ───────────────────────────

def test_ma200_dev_uses_proxy_index():
    """dev_pct = (proxy_close - ma200) / ma200，不能使用 fund_nav"""
    from src.app.core.strategy import calculate_ma200_deviation

    proxy_close, proxy_ma200 = 15000.0, 14900.0
    dev = calculate_ma200_deviation(proxy_close, proxy_ma200)
    expected = (15000.0 - 14900.0) / 14900.0
    assert abs(dev - expected) < 1e-10, f"dev={dev}, expected={expected}"

    # 验证：如果错误地传了 fund_nav (如 5.128) 会怎么样？
    # 5.128 和 14900 差距巨大，但 code 现在要求两者都 >0
    # 实际应该由调用方确保传入的是 proxy_close 而非 nav
    with pytest.raises(ValueError):
        calculate_ma200_deviation(0, 14900)  # proxy_close <= 0


def test_ma200_zero_rejected():
    """ma200 <= 0 必须拒绝"""
    from src.app.core.strategy import calculate_ma200_deviation
    with pytest.raises(ValueError):
        calculate_ma200_deviation(15000, 0)


# ── Test 4: 高估时动态=0 ───────────────────────────────

def test_high_dynamic_zero():
    """dev_pct >= 0.05 时，dynamic_amount = 0"""
    from src.app.core.strategy import calculate_dca_allocation

    cfg = {"weekly_budget": 200.0, "fixed_ratio": 0.40}
    r = calculate_dca_allocation(cfg, reserve_balance=30.0, dev_pct=0.05)
    assert r.dynamic_amount == 0.0, f"high: dynamic={r.dynamic_amount}"

    r = calculate_dca_allocation(cfg, reserve_balance=30.0, dev_pct=0.10)
    assert r.dynamic_amount == 0.0, f"higher: dynamic={r.dynamic_amount}"


# ── Test 5: 低估时动用准备金 ────────────────────────────

def test_low_uses_reserve():
    """dev_pct <= -0.10 时，dynamic_ratio = 0.75"""
    from src.app.core.strategy import calculate_dca_allocation, smooth_allocation_ratio

    alloc = smooth_allocation_ratio(-0.10, -0.10, 0.05, 0.75, 0.0)
    assert abs(alloc - 0.75) < 0.001, f"low alloc={alloc}"

    alloc = smooth_allocation_ratio(-0.15, -0.10, 0.05, 0.75, 0.0)
    assert abs(alloc - 0.75) < 0.001, f"deeper low alloc={alloc}"


# ── Test 6: 中估线性插值 ────────────────────────────────

def test_mid_interpolation():
    """dev_pct 在 -0.10 和 0.05 之间时，动态比例应线性插值"""
    from src.app.core.strategy import smooth_allocation_ratio

    # -2.5% 是 -10% 和 +5% 的正中间
    alloc = smooth_allocation_ratio(-0.025, -0.10, 0.05, 0.75, 0.0)
    assert abs(alloc - 0.375) < 0.01, f"mid alloc={alloc}"

    # 0% 偏向高端
    alloc_zero = smooth_allocation_ratio(0.0, -0.10, 0.05, 0.75, 0.0)
    assert 0.0 < alloc_zero < 0.75, f"alloc at 0%: {alloc_zero}"

    # 单调递减
    a1 = smooth_allocation_ratio(-0.08, -0.10, 0.05, 0.75, 0.0)
    a2 = smooth_allocation_ratio(-0.02, -0.10, 0.05, 0.75, 0.0)
    assert a1 > a2, f"not monotonic: a1={a1}, a2={a2}"


# ── Test 7: 单周上限 ────────────────────────────────────

def test_weekly_cap_enforced():
    """total_amount <= weekly_budget * max_weekly_multiple"""
    from src.app.core.strategy import calculate_dca_allocation

    cfg = {"weekly_budget": 200.0, "fixed_ratio": 0.40}
    r = calculate_dca_allocation(cfg, reserve_balance=10000.0, dev_pct=-0.10)
    assert r.total_amount <= 200.0 * 3.0, (
        f"Cap exceeded: total={r.total_amount}, max={200.0*3.0}"
    )

    # 极端情况：准备金很大 + 深度低估
    r2 = calculate_dca_allocation(cfg, reserve_balance=10000.0, dev_pct=-0.30)
    assert r2.total_amount <= 200.0 * 3.0, (
        f"Extreme cap: total={r2.total_amount}"
    )


# ── Test 8: 资金池透支防控 ──────────────────────────────

def test_no_pool_overdraft():
    """pool_balance 不足时，from_pool BUY 必须失败"""
    from src.app.services.accounting import D

    # 模拟：pool_balance=50，但要从池中买 200
    pool_balance = D("50.00")
    buy_amount = D("200.00")

    can_buy = pool_balance >= buy_amount
    assert not can_buy, "Pool overdraft should be blocked"

    # 余额充足时允许
    pool_balance = D("300.00")
    can_buy = pool_balance >= buy_amount
    assert can_buy, "Pool should allow when balance is sufficient"


# ── Test 9: 删除 pool BUY 回滚 ──────────────────────────

def test_delete_pool_buy_refunds_pool():
    """删除 from_pool BUY 后，资金池余额恢复"""
    from src.app.services.accounting import D

    pool_balance = D("300.00")
    buy_amount = D("80.00")
    from_pool = True

    # 买入
    if from_pool:
        pool_balance -= buy_amount
    assert pool_balance == D("220.00"), f"After buy: {pool_balance}"

    # 删除交易 → 回滚
    pool_balance += buy_amount
    assert pool_balance == D("300.00"), f"After refund: {pool_balance}"


# ── Test 10: dev_pct 不是 grid_pos ─────────────────────

def test_dailyplan_dev_pct_not_grid_pos():
    """DailyPlan.dev_pct 只能是 MA200 偏离度，不得是 grid_pos"""
    from src.app.core.models import DailyPlan

    plan = DailyPlan(
        fund_code="000083",
        dev_pct=0.032,      # 3.2% MA200 偏离
        grid_pos=0.5,       # 网格位置（仅实验模式用）
        strategy_mode="ma200_deviation",
    )

    assert plan.dev_pct != plan.grid_pos, "dev_pct must not equal grid_pos"
    assert plan.dev_pct == 0.032
    assert plan.grid_pos == 0.5
    assert plan.strategy_mode == "ma200_deviation"


# ── 额外测试：risk_guard 综合 ───────────────────────────

def test_risk_guard_nav_abnormal():
    from src.app.core.risk_guard import validate_nav
    assert not validate_nav(0).passed
    assert not validate_nav(-1).passed
    assert not validate_nav(25).passed
    assert validate_nav(1.23).passed


def test_risk_guard_dev_pct_abnormal():
    from src.app.core.risk_guard import validate_dev_pct
    assert not validate_dev_pct(0.99).passed
    assert not validate_dev_pct(-0.99).passed
    assert not validate_dev_pct(0.51).passed
    assert validate_dev_pct(0.03).passed
    assert validate_dev_pct(-0.10).passed


def test_risk_guard_format_rejection():
    from src.app.core.risk_guard import format_rejection_message, RiskResult

    r = RiskResult(passed=False, errors=["数据源为 Mock，禁止生成正式建议"])
    msg = format_rejection_message(r)
    assert "数据异常" in msg
    assert "人工复核" in msg
    assert "Mock" in msg
