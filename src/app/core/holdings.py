#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓计算模块
- Decimal 精度运算
- 持有/累计盈亏计算
- 盈亏平衡净值计算
"""

import pandas as pd
import numpy as np
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

# 设置内部 decimal 精度
getcontext().prec = 28
Q2 = Decimal("0.01")  # 金额精度：2位小数
Q4 = Decimal("0.0001")  # 净值精度：4位小数
Q_SHARES = Decimal("0.01")  # 份额精度：2位小数


def D(x):
    """转换为Decimal类型"""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return Decimal("0")  # Or handle appropriately
    return x if isinstance(x, Decimal) else Decimal(str(x))


def quant_amt(x):
    """金额量化到2位小数"""
    return D(x).quantize(Q2, rounding=ROUND_HALF_UP)


def quant_nav(x):
    """净值量化到4位小数"""
    return D(x).quantize(Q4, rounding=ROUND_HALF_UP)


def quant_shares(x):
    """份额量化到2位小数"""
    return D(x).quantize(Q_SHARES, rounding=ROUND_HALF_UP)


class HoldingsCalculator:
    """持仓计算器"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化持仓计算器

        Args:
            config: 配置字典
        """
        self.config = config
        self.holdings_config = config.get("manual_holdings", {})

    def get_holdings_info(self) -> Dict[str, Any]:
        """
        获取持仓基本信息

        Returns:
            持仓信息字典
        """
        if self.holdings_config.get("enabled", False):
            return {
                "units_left": self.holdings_config["units_left"],
                "avg_cost": self.holdings_config["avg_cost"],
                "realized_pnl": self.holdings_config["realized_pnl"],
                "source": "手动配置",
            }
        else:
            # 这里可以扩展为从CSV或其他数据源读取
            return {
                "units_left": 0.0,
                "avg_cost": 0.0,
                "realized_pnl": 0.0,
                "source": "未配置",
            }

    def calculate_holdings_precise(
        self,
        units: float,
        avg_cost: float,
        current_nav: float,
        realized_pnl: float = 0.0,
    ) -> Dict[str, Any]:
        """
        使用Decimal精确计算持仓

        Args:
            units: 持有份额
            avg_cost: 平均成本（含费）
            current_nav: 当前净值
            realized_pnl: 已实现盈亏

        Returns:
            精确计算结果
        """
        # 转换为Decimal
        units_dec = D(units)
        avg_cost_dec = D(avg_cost)
        current_nav_dec = D(current_nav)
        realized_pnl_dec = D(realized_pnl)

        # 计算持仓成本
        cost_left = quant_amt(units_dec * avg_cost_dec)

        # 计算当前市值
        mtm_value = quant_amt(units_dec * current_nav_dec)

        # 计算未实现盈亏
        unrealized_pnl = quant_amt(mtm_value - cost_left)

        # 计算未实现盈亏百分比
        if cost_left > 0:
            unrealized_pct = quant_amt((unrealized_pnl / cost_left) * 100)
        else:
            unrealized_pct = Decimal("0.00")

        # 计算累计盈亏
        total_pnl = quant_amt(unrealized_pnl + realized_pnl_dec)

        # 计算盈亏平衡净值
        breakeven_nav = avg_cost_dec if units_dec > 0 else Decimal("0")

        return {
            "units": quant_shares(units_dec),
            "avg_cost": quant_nav(avg_cost_dec),
            "cost_disp": cost_left,
            "m2m_disp": mtm_value,
            "pnl_disp": unrealized_pnl,
            "unrealized_pct": unrealized_pct,
            "total_pnl": total_pnl,
            "breakeven_nav": quant_nav(breakeven_nav),
            "realized_pnl": realized_pnl_dec,
        }

    def calculate_holdings_summary(self, current_nav: float) -> Dict[str, Any]:
        """
        计算持仓汇总信息

        Args:
            current_nav: 当前净值

        Returns:
            持仓汇总信息
        """
        holdings = self.get_holdings_info()

        if holdings["units_left"] <= 0:
            return {
                "status": "无持仓",
                "units": 0.0,
                "avg_cost": 0.0,
                "current_nav": current_nav,
                "market_value": 0.0,
                "unrealized_pnl": 0.0,
                "unrealized_pct": 0.0,
                "total_pnl": holdings["realized_pnl"],
                "breakeven_nav": 0.0,
            }

        # 精确计算
        precise_result = self.calculate_holdings_precise(
            holdings["units_left"],
            holdings["avg_cost"],
            current_nav,
            holdings["realized_pnl"],
        )

        return {
            "status": "有持仓",
            "units": float(precise_result["units"]),
            "avg_cost": float(precise_result["avg_cost"]),
            "current_nav": current_nav,
            "market_value": float(precise_result["m2m_disp"]),
            "unrealized_pnl": float(precise_result["pnl_disp"]),
            "unrealized_pct": float(precise_result["unrealized_pct"]),
            "total_pnl": float(precise_result["total_pnl"]),
            "breakeven_nav": float(precise_result["breakeven_nav"]),
        }

    def generate_holdings_df(self, holdings_summary: Dict[str, Any]) -> pd.DataFrame:
        """
        生成持仓明细DataFrame

        Args:
            holdings_summary: 持仓汇总信息

        Returns:
            持仓明细表格
        """
        if holdings_summary["status"] == "无持仓":
            return pd.DataFrame()

        data = {
            "项目": [
                "持有份额",
                "平均成本",
                "当前净值",
                "持仓市值",
                "未实现盈亏",
                "盈亏比例",
                "累计盈亏",
                "盈亏平衡净值",
            ],
            "数值": [
                f"{holdings_summary['units']:.4f}",
                f"¥{holdings_summary['avg_cost']:.4f}",
                f"¥{holdings_summary['current_nav']:.4f}",
                f"¥{holdings_summary['market_value']:.2f}",
                f"¥{holdings_summary['unrealized_pnl']:.2f}",
                f"{holdings_summary['unrealized_pct']:.2f}%",
                f"¥{holdings_summary['total_pnl']:.2f}",
                f"¥{holdings_summary['breakeven_nav']:.4f}",
            ],
            "说明": [
                "剩余持有份额",
                "含费用的平均成本",
                "最新基金净值",
                "按当前净值计算的市值",
                "未实现盈亏金额",
                "未实现盈亏占成本比例",
                "包含已实现的累计盈亏",
                "达到盈亏平衡的净值",
            ],
        }

        return pd.DataFrame(data)

    def calculate_roi_metrics(self, holdings_summary: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算ROI相关指标

        Args:
            holdings_summary: 持仓汇总信息

        Returns:
            ROI指标字典
        """
        if holdings_summary["status"] == "无持仓":
            return {}

        # 计算年化收益率（简化计算）
        # 这里可以根据实际持有时间计算更准确的年化收益率

        # 计算夏普比率（简化，假设无风险利率为3%）
        risk_free_rate = 0.03
        if holdings_summary["unrealized_pct"] != 0:
            # 简化的夏普比率计算
            excess_return = (holdings_summary["unrealized_pct"] / 100) - risk_free_rate
            # 假设波动率为20%（实际应该根据历史数据计算）
            volatility = 0.20
            sharpe_ratio = excess_return / volatility if volatility > 0 else 0
        else:
            sharpe_ratio = 0

        return {
            "unrealized_roi": holdings_summary["unrealized_pct"],
            "total_roi": (
                (holdings_summary["total_pnl"] / holdings_summary["market_value"]) * 100
                if holdings_summary["market_value"] > 0
                else 0
            ),
            "sharpe_ratio": sharpe_ratio,
            "breakeven_roi": (
                (
                    (
                        holdings_summary["breakeven_nav"]
                        - holdings_summary["current_nav"]
                    )
                    / holdings_summary["current_nav"]
                )
                * 100
                if holdings_summary["current_nav"] > 0
                else 0
            ),
        }

    def export_holdings_csv(
        self, holdings_summary: Dict[str, Any], filename: str = "holdings_export.csv"
    ) -> str:
        """
        导出持仓信息到CSV

        Args:
            holdings_summary: 持仓汇总信息
            filename: 导出文件名

        Returns:
            导出文件路径
        """
        if holdings_summary["status"] == "无持仓":
            return ""

        # 创建导出数据
        export_data = {
            "导出时间": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            "基金代码": [self.config.get("fund_code", "N/A")],
            "基金名称": [self.config.get("fund_name", "N/A")],
            "持有份额": [holdings_summary["units"]],
            "平均成本": [holdings_summary["avg_cost"]],
            "当前净值": [holdings_summary["current_nav"]],
            "持仓市值": [holdings_summary["market_value"]],
            "未实现盈亏": [holdings_summary["unrealized_pnl"]],
            "未实现盈亏比例": [f"{holdings_summary['unrealized_pct']:.2f}%"],
            "累计盈亏": [holdings_summary["total_pnl"]],
            "盈亏平衡净值": [holdings_summary["breakeven_nav"]],
        }

        df = pd.DataFrame(export_data)
        df.to_csv(filename, index=False, encoding="utf-8-sig")

        return filename


def format_currency(amount: float, decimals: int = 2) -> str:
    """格式化货币显示"""
    if amount >= 0:
        return f"¥{amount:.{decimals}f}"
    else:
        return f"-¥{abs(amount):.{decimals}f}"


def format_percentage(value: float, decimals: int = 2) -> str:
    """格式化百分比显示"""
    if value >= 0:
        return f"+{value:.{decimals}f}%"
    else:
        return f"{value:.{decimals}f}%"


if __name__ == "__main__":
    # 测试持仓计算
    print("持仓计算模块测试")

    # 模拟配置
    test_config = {
        "fund_code": "000083",
        "fund_name": "汇添富消费行业混合",
        "manual_holdings": {
            "enabled": True,
            "units_left": 6.63,
            "avg_cost": 6.8627,
            "realized_pnl": -7.24,
        },
    }

    # 创建计算器
    calculator = HoldingsCalculator(test_config)

    # 测试持仓信息
    holdings = calculator.get_holdings_info()
    print(f"\n持仓信息:")
    print(f"  份额: {holdings['units_left']}")
    print(f"  成本: {holdings['avg_cost']}")
    print(f"  已实现盈亏: {holdings['realized_pnl']}")

    # 测试精确计算
    current_nav = 4.9920
    precise_result = calculator.calculate_holdings_precise(
        holdings["units_left"],
        holdings["avg_cost"],
        current_nav,
        holdings["realized_pnl"],
    )

    print(f"\n精确计算结果:")
    print(f"  持仓市值: {precise_result['m2m_disp']}")
    print(f"  未实现盈亏: {precise_result['pnl_disp']}")
    print(f"  盈亏比例: {precise_result['unrealized_pct']}%")
    print(f"  累计盈亏: {precise_result['total_pnl']}")

    # 测试持仓汇总
    summary = calculator.calculate_holdings_summary(current_nav)
    print(f"\n持仓汇总:")
    print(f"  状态: {summary['status']}")
    print(f"  市值: {summary['market_value']:.2f}")
    print(f"  盈亏: {summary['unrealized_pnl']:.2f} ({summary['unrealized_pct']:.2f}%)")

    # 测试ROI指标
    roi_metrics = calculator.calculate_roi_metrics(summary)
    print(f"\nROI指标:")
    print(f"  未实现ROI: {roi_metrics['unrealized_roi']:.2f}%")
    print(f"  夏普比率: {roi_metrics['sharpe_ratio']:.3f}")
