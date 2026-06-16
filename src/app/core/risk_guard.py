#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险防护模块

所有实盘建议在输出前必须经过此模块验证。
任何一项不通过，系统只允许输出"数据异常，需要人工复核"，
不得生成任何形式的具体买入建议。

规则：
    1. source == "Mock" / "mock" → 禁止建议
    2. nav 异常（≤0 或 >20）→ 禁止建议
    3. ma200 异常（≤0）→ 禁止建议
    4. dev_pct 异常（abs > 0.5）→ 禁止建议
    5. reserve_after < 0 → 禁止建议
    6. total_amount > weekly_budget × max_weekly_multiple → 禁止建议
"""

from dataclasses import dataclass, field
from typing import List, Optional
from decimal import Decimal


# ── 常量 ────────────────────────────────────────────────

MAX_NAV = Decimal("20.0")
MAX_DEV_PCT_ABS = 0.50  # ±50% 偏离视为异常
MAX_WEEKLY_MULTIPLE = 3.0


@dataclass
class RiskResult:
    """风险检查结果"""
    passed: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ── 单项验证 ────────────────────────────────────────────

def validate_nav(nav: float) -> RiskResult:
    """验证基金净值"""
    errors = []
    if nav is None:
        errors.append("NAV 为空")
    elif nav <= 0:
        errors.append(f"NAV 异常: {nav}，必须 > 0")
    elif nav > 20:
        errors.append(f"NAV 异常: {nav}，超过上限 {MAX_NAV}")
    return RiskResult(passed=len(errors) == 0, errors=errors)


def validate_market_snapshot(
    proxy_close: float,
    ma200: float,
    source: str,
) -> RiskResult:
    """验证市场数据快照"""
    errors = []

    # 数据源检查
    if source.lower() == "mock":
        errors.append(f"数据源为 Mock，不可用于实盘建议")

    # 代理指数价格
    if proxy_close is None or proxy_close <= 0:
        errors.append(f"代理指数收盘价异常: {proxy_close}")

    # MA200
    if ma200 is None or ma200 <= 0:
        errors.append(f"MA200 异常: {ma200}，必须 > 0")

    return RiskResult(passed=len(errors) == 0, errors=errors)


def validate_data_source(source: str) -> RiskResult:
    """验证数据源"""
    errors = []
    if not source:
        errors.append("数据源为空")
    elif source.lower() == "mock":
        errors.append("数据源为 Mock，禁止生成正式建议")
    return RiskResult(passed=len(errors) == 0, errors=errors)


def validate_dev_pct(dev_pct: float) -> RiskResult:
    """验证 MA200 偏离度"""
    errors = []
    if dev_pct is None:
        errors.append("dev_pct 为空")
    elif abs(dev_pct) > MAX_DEV_PCT_ABS:
        errors.append(
            f"dev_pct 异常: {dev_pct:.4f}（{dev_pct*100:.2f}%），"
            f"超出允许范围 ±{MAX_DEV_PCT_ABS*100:.0f}%"
        )
    return RiskResult(passed=len(errors) == 0, errors=errors)


def validate_daily_plan(
    plan,
    weekly_budget: float = 200.0,
    max_weekly_multiple: float = MAX_WEEKLY_MULTIPLE,
) -> RiskResult:
    """验证定投计划"""
    errors = []

    # 准备金非负
    if plan.reserve_after is not None and plan.reserve_after < 0:
        errors.append(
            f"准备金余额为负: {plan.reserve_after:.2f}，不允许透支"
        )

    # 单周上限
    weekly_cap = weekly_budget * max_weekly_multiple
    if plan.total_amount is not None and plan.total_amount > weekly_cap:
        errors.append(
            f"单周定投金额 {plan.total_amount:.2f} 超出上限 {weekly_cap:.2f}"
            f"（weekly_budget × {max_weekly_multiple}）"
        )

    # dev_pct 必须是合法值
    if plan.dev_pct is not None:
        dev_result = validate_dev_pct(plan.dev_pct)
        errors.extend(dev_result.errors)

    return RiskResult(passed=len(errors) == 0, errors=errors)


# ── 综合判定 ────────────────────────────────────────────

def advice_allowed(
    nav: Optional[float] = None,
    proxy_close: Optional[float] = None,
    ma200: Optional[float] = None,
    dev_pct: Optional[float] = None,
    source: str = "",
    plan=None,
    weekly_budget: float = 200.0,
) -> RiskResult:
    """
    综合判定：是否允许生成投资建议。

    任一检查不通过 → passed=False，前端只能显示"数据异常，需要人工复核"。

    Args:
        nav: 基金净值
        proxy_close: 代理指数收盘价
        ma200: MA200 值
        dev_pct: MA200 偏离度
        source: 数据源
        plan: DailyPlan 对象（可选）
        weekly_budget: 周预算

    Returns:
        RiskResult（含所有错误信息）
    """
    all_errors: List[str] = []
    all_warnings: List[str] = []

    # 1. 数据源
    r = validate_data_source(source)
    all_errors.extend(r.errors)

    # 2. NAV
    if nav is not None:
        r = validate_nav(nav)
        all_errors.extend(r.errors)

    # 3. 市场快照
    if proxy_close is not None or ma200 is not None:
        r = validate_market_snapshot(
            proxy_close or 0, ma200 or 0, source
        )
        # 避免重复（validate_market_snapshot 已检查 source）
        for e in r.errors:
            if e not in all_errors:
                all_errors.append(e)

    # 4. dev_pct
    if dev_pct is not None:
        r = validate_dev_pct(dev_pct)
        all_errors.extend(r.errors)

    # 5. 定投计划
    if plan is not None:
        r = validate_daily_plan(plan, weekly_budget)
        all_errors.extend(r.errors)

    return RiskResult(
        passed=len(all_errors) == 0,
        errors=all_errors,
        warnings=all_warnings,
    )


def format_rejection_message(result: RiskResult) -> str:
    """格式化拒绝消息"""
    if result.passed:
        return ""
    lines = ["## ⚠️ 数据异常，需要人工复核", ""]
    for i, err in enumerate(result.errors, 1):
        lines.append(f"{i}. {err}")
    lines.append("")
    lines.append("> 系统已自动阻断本次建议生成，请检查数据源后重试。")
    return "\n".join(lines)
