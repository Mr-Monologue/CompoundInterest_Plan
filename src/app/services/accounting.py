#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
会计核算模块

所有金额、成本、收益率的最终展示必须通过 Decimal 计算。
支付宝口径：
    持仓市值 = 持有份额 × 最新净值
    持有成本 = 持有份额 × 持仓成本价
    持有收益 = 持仓市值 - 持有成本
    持有收益率 = 持有收益 / 持有成本 × 100%

精度规则：
    金额 → 2 位小数（quantize Q2）
    净值 → 4 位小数（quantize Q4）
    份额 → 平台显示精度（quantize Q_SHARES）
    收益率 → 2 位小数（quantize Q2）
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext
from dataclasses import dataclass
from typing import Optional

# 全局精度
getcontext().prec = 28

# 量化精度
Q2 = Decimal("0.01")       # 金额：2 位
Q4 = Decimal("0.0001")     # 净值：4 位
Q_SHARES = Decimal("0.01") # 份额：2 位


def D(x) -> Decimal:
    """安全转换为 Decimal"""
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(x)


@dataclass
class HoldingResult:
    """持仓计算结果"""
    units: Decimal = Decimal("0")           # 持有份额
    avg_cost: Decimal = Decimal("0")        # 平均成本（含费）
    current_nav: Decimal = Decimal("0")     # 当前净值
    market_value: Decimal = Decimal("0")    # 持仓市值
    cost_basis: Decimal = Decimal("0")      # 持有成本
    unrealized_pnl: Decimal = Decimal("0")  # 未实现盈亏
    unrealized_pct: Decimal = Decimal("0")  # 未实现盈亏率
    realized_pnl: Decimal = Decimal("0")    # 已实现盈亏
    total_pnl: Decimal = Decimal("0")       # 累计盈亏
    breakeven_nav: Decimal = Decimal("0")   # 盈亏平衡净值
    source: str = "accounting"              # 计算来源


def calculate_holdings(
    units: float,
    avg_cost: float,
    current_nav: float,
    realized_pnl: float = 0.0,
) -> HoldingResult:
    """
    持仓计算（支付宝口径）。

    Args:
        units: 持有份额
        avg_cost: 持仓成本价（含费）
        current_nav: 当前净值
        realized_pnl: 已实现盈亏

    Raises:
        ValueError: 如果持仓数据无效
    """
    units_d = D(units)
    avg_cost_d = D(avg_cost)
    nav_d = D(current_nav)
    realized_d = D(realized_pnl)

    if units_d < 0:
        raise ValueError(f"持有份额不能为负: {units}")
    if nav_d <= 0:
        raise ValueError(f"净值必须 > 0: {current_nav}")

    # 支付宝口径
    market_value = (units_d * nav_d).quantize(Q2, rounding=ROUND_HALF_UP)
    cost_basis = (units_d * avg_cost_d).quantize(Q2, rounding=ROUND_HALF_UP)
    unrealized_pnl = (market_value - cost_basis).quantize(Q2, rounding=ROUND_HALF_UP)

    # 收益率必须从原始精度计算，避免中间取整误差
    # 先算原始未实现盈亏和原始成本，再算百分比，最后取整
    raw_unrealized = units_d * nav_d - units_d * avg_cost_d
    raw_cost = units_d * avg_cost_d
    if raw_cost > 0:
        unrealized_pct = ((raw_unrealized / raw_cost) * Decimal("100")).quantize(
            Q2, rounding=ROUND_HALF_UP
        )
    else:
        unrealized_pct = Decimal("0.00")

    total_pnl = (unrealized_pnl + realized_d).quantize(Q2, rounding=ROUND_HALF_UP)
    breakeven_nav = avg_cost_d.quantize(Q4, rounding=ROUND_HALF_UP)

    return HoldingResult(
        units=units_d,
        avg_cost=avg_cost_d.quantize(Q4, rounding=ROUND_HALF_UP),
        current_nav=nav_d.quantize(Q4, rounding=ROUND_HALF_UP),
        market_value=market_value,
        cost_basis=cost_basis,
        unrealized_pnl=unrealized_pnl,
        unrealized_pct=unrealized_pct,
        realized_pnl=realized_d.quantize(Q2, rounding=ROUND_HALF_UP),
        total_pnl=total_pnl,
        breakeven_nav=breakeven_nav,
        source="accounting",
    )


def format_currency(amount: Decimal, sign: bool = True) -> str:
    """格式化金额显示"""
    val = float(amount)
    if sign and val >= 0:
        return f"¥{val:,.2f}"
    elif val < 0:
        return f"-¥{abs(val):,.2f}"
    else:
        return f"¥{val:,.2f}"


def format_pct(value: Decimal) -> str:
    """格式化百分比显示"""
    val = float(value)
    if val >= 0:
        return f"+{val:.2f}%"
    return f"{val:.2f}%"


# ── 支付宝展示结果常量验证 ──────────────────────────────

def alipay_reference_values() -> HoldingResult:
    """
    返回已知正确的结果集，用于测试验证。

    输入：
        units=6.63, avg_cost=6.8627, nav=4.9920, realized=-7.24

    期望（支付宝口径）：
        market_value = 33.10
        unrealized_pnl = -12.40
        unrealized_pct = -27.26
        total_pnl = -19.64
    """
    return calculate_holdings(
        units=6.63,
        avg_cost=6.8627,
        current_nav=4.9920,
        realized_pnl=-7.24,
    )
