#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号计算模块
- MA200 偏离计算
- 阈值/平滑映射
- 动态定投比例计算
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple, Optional
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP


def calculate_ma200_deviation(
    df: pd.DataFrame, current_price: Optional[float] = None
) -> Dict[str, Any]:
    """
    计算MA200偏离度

    Args:
        df: 包含close和ma200列的DataFrame
        current_price: 当前价格，如果为None则使用最新收盘价

    Returns:
        包含偏离度信息的字典
    """
    if df.empty or "close" not in df.columns or "ma200" not in df.columns:
        raise ValueError("DataFrame必须包含close和ma200列")

    # 获取最新数据
    latest = df.iloc[-1]
    current_price = current_price or latest["close"]
    current_ma200 = latest["ma200"]

    # 计算偏离度
    deviation_pct = ((current_price - current_ma200) / current_ma200) * 100

    # 判断估值水平
    if deviation_pct <= -10.0:
        level = "low"  # 低估
    elif deviation_pct <= 5.0:
        level = "mid"  # 合理
    else:
        level = "high"  # 偏高

    return {
        "current_price": current_price,
        "ma200": current_ma200,
        "deviation_pct": deviation_pct,
        "level": level,
        "date": latest["date"] if "date" in latest else datetime.now(),
    }


def smooth_allocation_ratio(
    deviation_pct: float,
    low_threshold: float,
    mid_threshold: float,
    low_ratio: float,
    high_ratio: float,
) -> float:
    """
    平滑映射分配比例，避免阈值跳跃

    Args:
        deviation_pct: MA200偏离百分比
        low_threshold: 低估阈值
        mid_threshold: 中估阈值
        low_ratio: 低估时的分配比例
        high_ratio: 高估时的分配比例

    Returns:
        平滑后的分配比例
    """
    if deviation_pct <= low_threshold:
        return low_ratio
    elif deviation_pct >= mid_threshold:
        return high_ratio
    else:
        # 在阈值之间进行线性插值
        range_size = mid_threshold - low_threshold
        position = (deviation_pct - low_threshold) / range_size
        return low_ratio + (high_ratio - low_ratio) * position


def calculate_dca_allocation(
    config: Dict[str, Any], state: Dict[str, Any], deviation_info: Dict[str, Any]
) -> Dict[str, Any]:
    """
    计算动态定投分配

    Args:
        config: 配置字典
        state: 状态字典
        deviation_info: MA200偏离信息

    Returns:
        定投分配结果
    """
    weekly_budget = config["weekly_budget"]
    fixed_ratio = config["fixed_ratio"]
    reserve_cap_months = config["reserve_cap_months"]
    max_weekly_multiple = config["max_weekly_multiple"]

    # 固定部分
    fixed_amount = weekly_budget * fixed_ratio

    # 动态部分（基于估值水平）
    level = deviation_info["level"]
    deviation_pct = deviation_info["deviation_pct"]

    if level == "low":
        alloc_ratio = config["alloc_low"]
    elif level == "mid":
        # 使用平滑映射
        alloc_ratio = smooth_allocation_ratio(
            deviation_pct,
            config["ma200_low"],
            config["ma200_mid"],
            config["alloc_low"],
            config["alloc_high"],
        )
    else:  # high
        alloc_ratio = config["alloc_high"]

    # 计算准备金使用金额
    reserve_balance = state.get("reserve_balance", 0.0)
    reserve_cap = weekly_budget * reserve_cap_months * 4  # 月转周

    # 限制准备金使用
    available_reserve = min(reserve_balance, reserve_cap)
    dynamic_amount = available_reserve * alloc_ratio

    # 限制最大倍数
    max_dynamic = weekly_budget * max_weekly_multiple
    dynamic_amount = min(dynamic_amount, max_dynamic)

    # 总定投金额
    total_amount = fixed_amount + dynamic_amount

    # 更新准备金余额
    reserve_after = reserve_balance - dynamic_amount

    return {
        "fixed_amount": fixed_amount,
        "dynamic_amount": dynamic_amount,
        "total_amount": total_amount,
        "alloc_ratio": alloc_ratio,
        "reserve_before": reserve_balance,
        "reserve_after": reserve_after,
        "level": level,
        "deviation_pct": deviation_pct,
        "weekly_budget": weekly_budget,
    }


def generate_dca_plan_df(allocation: Dict[str, Any]) -> pd.DataFrame:
    """
    生成定投计划DataFrame

    Args:
        allocation: 定投分配结果

    Returns:
        定投计划表格
    """
    data = {
        "项目": ["固定定投", "动态定投", "总定投", "准备金变化"],
        "金额": [
            f"¥{allocation['fixed_amount']:.2f}",
            f"¥{allocation['dynamic_amount']:.2f}",
            f"¥{allocation['total_amount']:.2f}",
            f"¥{allocation['reserve_before']:.2f} → ¥{allocation['reserve_after']:.2f}",
        ],
        "说明": [
            f"基础定投 ({allocation['weekly_budget'] * allocation.get('alloc_ratio', 0):.0f}%)",
            f"估值驱动 ({allocation['alloc_ratio']:.1%})",
            "本周建议申购金额",
            "预备金余额变化",
        ],
    }

    return pd.DataFrame(data)


def calculate_ma200_trend(df: pd.DataFrame, days: int = 30) -> Dict[str, Any]:
    """
    计算MA200趋势

    Args:
        df: 指数数据DataFrame
        days: 计算趋势的天数

    Returns:
        MA200趋势信息
    """
    if len(df) < days:
        return {"trend": "insufficient_data", "slope": 0, "change_pct": 0}

    # 获取最近N天的MA200数据
    recent_ma200 = df["ma200"].tail(days).dropna()

    if len(recent_ma200) < 2:
        return {"trend": "insufficient_data", "slope": 0, "change_pct": 0}

    # 计算线性回归斜率
    x = np.arange(len(recent_ma200))
    y = recent_ma200.values

    # 简单线性回归
    slope = np.polyfit(x, y, 1)[0]

    # 计算变化百分比
    start_ma200 = recent_ma200.iloc[0]
    end_ma200 = recent_ma200.iloc[-1]
    change_pct = ((end_ma200 - start_ma200) / start_ma200) * 100

    # 判断趋势
    if slope > 0.01:  # 斜率阈值
        trend = "上升"
    elif slope < -0.01:
        trend = "下降"
    else:
        trend = "横盘"

    return {
        "trend": trend,
        "slope": slope,
        "change_pct": change_pct,
        "start_ma200": start_ma200,
        "end_ma200": end_ma200,
        "days": days,
    }


def get_buy_signals(df: pd.DataFrame, threshold: float = -5.0) -> pd.DataFrame:
    """
    获取买点信号

    Args:
        df: 指数数据DataFrame
        threshold: 买点阈值（偏离度）

    Returns:
        买点信号DataFrame
    """
    if df.empty:
        return pd.DataFrame()

    # 计算每日偏离度
    df = df.copy()
    df["deviation_pct"] = ((df["close"] - df["ma200"]) / df["ma200"]) * 100

    # 筛选买点
    buy_signals = df[df["deviation_pct"] <= threshold].copy()

    if buy_signals.empty:
        return pd.DataFrame()

    # 添加信号强度
    buy_signals["signal_strength"] = abs(buy_signals["deviation_pct"]) / abs(threshold)

    # 按日期排序
    buy_signals = buy_signals.sort_values("date", ascending=False)

    return buy_signals[["date", "close", "ma200", "deviation_pct", "signal_strength"]]


if __name__ == "__main__":
    # 测试信号计算
    print("信号计算模块测试")

    # 模拟数据
    dates = pd.date_range("2023-01-01", periods=250, freq="D")
    np.random.seed(42)
    prices = 100 + np.cumsum(np.random.randn(250) * 0.5)
    ma200 = prices.rolling(200).mean()

    df = pd.DataFrame({"date": dates, "close": prices, "ma200": ma200})

    # 测试MA200偏离计算
    deviation_info = calculate_ma200_deviation(df)
    print(f"\nMA200偏离信息:")
    print(f"  当前价格: {deviation_info['current_price']:.2f}")
    print(f"  MA200: {deviation_info['ma200']:.2f}")
    print(f"  偏离度: {deviation_info['deviation_pct']:.2f}%")
    print(f"  估值水平: {deviation_info['level']}")

    # 测试平滑映射
    smooth_ratio = smooth_allocation_ratio(-5.0, -10.0, 5.0, 0.75, 0.0)
    print(f"\n平滑映射比例: {smooth_ratio:.1%}")

    # 测试趋势计算
    trend_info = calculate_ma200_trend(df)
    print(f"\nMA200趋势:")
    print(f"  趋势: {trend_info['trend']}")
    print(f"  斜率: {trend_info['slope']:.4f}")
    print(f"  变化: {trend_info['change_pct']:.2f}%")
