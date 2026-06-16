#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略内核 — MA200 偏离度动态定投

这是唯一的生产策略。所有实盘建议必须通过此模块计算。

核心参数（不可随意修改）：
    strategy_mode = "ma200_deviation"
    weekly_budget = 200.0
    fixed_ratio = 0.40
    ma200_low = -0.10     # ≤ -10% → 低估
    ma200_high = 0.05     # > +5% → 偏高
    alloc_low = 0.75      # 低估时动用 75% 准备金
    alloc_high = 0.0      # 高估时不动用准备金
    max_weekly_multiple = 3.0  # 单周总投入上限
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np
from datetime import datetime


# ── 策略常量 ────────────────────────────────────────────

STRATEGY_MODE = "ma200_deviation"

DEFAULT_PARAMS = {
    "weekly_budget": 200.0,
    "fixed_ratio": 0.40,
    "reserve_cap_months": 3,
    "max_weekly_multiple": 3.0,
    "ma200_low": -0.10,       # 低估阈值
    "ma200_high": 0.05,       # 偏高阈值
    "alloc_low": 0.75,        # 低估时动用准备金比例
    "alloc_mid_start": 0.75,  # 中估区间起点（对应 ma200_low）
    "alloc_mid_end": 0.0,     # 中估区间终点（对应 ma200_high）
    "alloc_high": 0.0,        # 高估时不动用
}

# ── MA200 偏离计算 ──────────────────────────────────────

def calculate_ma200_deviation(
    proxy_close: float,
    proxy_ma200: float,
) -> float:
    """
    计算 MA200 偏离度。

    Args:
        proxy_close: 代理指数收盘价
        proxy_ma200: 代理指数 MA200 值

    Returns:
        偏离度百分比（小数形式，如 -0.10 表示 -10%）

    Raises:
        ValueError: 如果 ma200 <= 0
    """
    if proxy_ma200 <= 0:
        raise ValueError(f"MA200 值异常: {proxy_ma200}，必须 > 0")
    if proxy_close <= 0:
        raise ValueError(f"代理指数收盘价异常: {proxy_close}，必须 > 0")
    return (proxy_close - proxy_ma200) / proxy_ma200


def determine_level(dev_pct: float) -> str:
    """
    根据 MA200 偏离度判定估值层级。

    Args:
        dev_pct: 偏离度（小数）

    Returns:
        "low" / "mid" / "high"
    """
    if dev_pct <= DEFAULT_PARAMS["ma200_low"]:
        return "low"
    elif dev_pct <= DEFAULT_PARAMS["ma200_high"]:
        return "mid"
    else:
        return "high"


def smooth_allocation_ratio(
    dev_pct: float,
    low_threshold: float = DEFAULT_PARAMS["ma200_low"],
    high_threshold: float = DEFAULT_PARAMS["ma200_high"],
    low_ratio: float = DEFAULT_PARAMS["alloc_low"],
    high_ratio: float = DEFAULT_PARAMS["alloc_high"],
) -> float:
    """
    平滑映射分配比例，在 [low_threshold, high_threshold] 区间内线性插值。

    - dev_pct ≤ low_threshold → low_ratio
    - dev_pct ≥ high_threshold → high_ratio
    - 中间 → 线性插值
    """
    if dev_pct <= low_threshold:
        return low_ratio
    elif dev_pct >= high_threshold:
        return high_ratio
    else:
        range_size = high_threshold - low_threshold
        position = (dev_pct - low_threshold) / range_size
        return low_ratio + (high_ratio - low_ratio) * position


# ── 定投分配计算 ────────────────────────────────────────

@dataclass
class DcaAllocation:
    """定投分配结果"""
    fund_code: str = ""
    fixed_amount: float = 0.0
    dynamic_amount: float = 0.0
    total_amount: float = 0.0
    alloc_ratio: float = 0.0
    reserve_before: float = 0.0
    reserve_after: float = 0.0
    level: str = "mid"
    dev_pct: float = 0.0
    weekly_budget: float = 200.0
    strategy_mode: str = STRATEGY_MODE


def calculate_dca_allocation(
    config: Dict[str, Any],
    reserve_balance: float,
    dev_pct: float,
) -> DcaAllocation:
    """
    计算动态定投分配。

    资金流逻辑：
        1. fixed_amount = weekly_budget × fixed_ratio （保底投入）
        2. reserve_inflow = weekly_budget × (1 - fixed_ratio) （每周流入准备金）
        3. reserve_before = min(reserve_balance + reserve_inflow, reserve_cap)
        4. dynamic_amount = reserve_before × alloc_ratio （根据估值水平）
        5. total_amount = fixed_amount + dynamic_amount
        6. 单周上限约束：total_amount ≤ weekly_budget × max_weekly_multiple
        7. reserve_after = reserve_before - dynamic_amount ≥ 0

    Args:
        config: 基金配置字典（含 weekly_budget, fixed_ratio 等）
        reserve_balance: 当前准备金余额
        dev_pct: MA200 偏离度

    Returns:
        DcaAllocation 对象
    """
    # 合并默认参数
    params = {**DEFAULT_PARAMS, **config}

    weekly_budget = float(params["weekly_budget"])
    fixed_ratio = float(params["fixed_ratio"])
    reserve_cap_months = int(params["reserve_cap_months"])
    max_weekly_multiple = float(params["max_weekly_multiple"])

    # 固定定投
    fixed_amount = weekly_budget * fixed_ratio

    # 估值层级 & 分配比例
    level = determine_level(dev_pct)
    if level == "low":
        alloc_ratio = params["alloc_low"]
    elif level == "high":
        alloc_ratio = params["alloc_high"]
    else:  # mid
        alloc_ratio = smooth_allocation_ratio(
            dev_pct,
            params["ma200_low"],
            params["ma200_high"],
            params["alloc_low"],
            params["alloc_high"],
        )

    # 准备金流入 + 上限
    reserve_inflow = weekly_budget * (1 - fixed_ratio)
    reserve_cap = weekly_budget * reserve_cap_months * 4  # 月转周
    reserve_before = min(reserve_balance + reserve_inflow, reserve_cap)

    # 动态定投金额
    dynamic_amount = reserve_before * alloc_ratio

    # 单周上限约束
    weekly_cap_total = weekly_budget * max_weekly_multiple
    max_dynamic = max(0.0, weekly_cap_total - fixed_amount)
    dynamic_amount = min(dynamic_amount, max_dynamic)

    # 总定投
    total_amount = fixed_amount + dynamic_amount

    # 准备金结算
    reserve_after = max(0.0, reserve_before - dynamic_amount)

    return DcaAllocation(
        fixed_amount=fixed_amount,
        dynamic_amount=dynamic_amount,
        total_amount=total_amount,
        alloc_ratio=alloc_ratio,
        reserve_before=reserve_before,
        reserve_after=reserve_after,
        level=level,
        dev_pct=dev_pct,
        weekly_budget=weekly_budget,
        strategy_mode=STRATEGY_MODE,
    )


# ── MA200 趋势计算 ──────────────────────────────────────

def calculate_ma200_trend(
    df: pd.DataFrame, days: int = 30
) -> Dict[str, Any]:
    """计算 MA200 趋势（上升/下降/横盘）"""
    if len(df) < days:
        return {"trend": "insufficient_data", "slope": 0, "change_pct": 0}

    recent = df["ma200"].tail(days).dropna()
    if len(recent) < 2:
        return {"trend": "insufficient_data", "slope": 0, "change_pct": 0}

    x = np.arange(len(recent))
    y = recent.values
    slope = np.polyfit(x, y, 1)[0]

    start_ma200 = float(recent.iloc[0])
    end_ma200 = float(recent.iloc[-1])
    change_pct = ((end_ma200 - start_ma200) / start_ma200) * 100 if start_ma200 > 0 else 0

    if slope > 0.01:
        trend = "上升"
    elif slope < -0.01:
        trend = "下降"
    else:
        trend = "横盘"

    return {
        "trend": trend,
        "slope": float(slope),
        "change_pct": change_pct,
        "start_ma200": start_ma200,
        "end_ma200": end_ma200,
        "days": days,
    }


# ── 生产策略入口 ────────────────────────────────────────

def get_production_strategy() -> Dict[str, Any]:
    """返回生产策略参数"""
    return {
        "strategy_mode": STRATEGY_MODE,
        "params": DEFAULT_PARAMS,
    }
