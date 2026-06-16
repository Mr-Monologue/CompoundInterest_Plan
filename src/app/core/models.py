#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据模型定义

所有实盘辅助相关的数据结构集中管理。
- Asset: 基金/资产定义
- Transaction: 交易记录
- DailyPlan: 每日（每周）定投计划
- PoolLedger: 资金池流水
- FundState: 基金运行状态
- NavSnapshot: 净值快照
- MarketSnapshot: 市场数据快照
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List


@dataclass
class Asset:
    """基金/资产定义"""
    fund_code: str                              # 基金代码，如 "000083"
    fund_name: str                              # 基金名称
    fund_name_en: str = ""                      # yfinance 代码，如 "000083.SZ"
    proxy_code: Optional[str] = None            # 代理指数代码，如 "000932"
    proxy_type: str = "INDEX"                   # 代理类型：INDEX
    proxy_index_en: str = ""                    # 代理指数 yfinance 代码，如 "000932.SS"
    weekly_budget: float = 200.0                # 周定投预算
    manual_holdings: dict = field(default_factory=lambda: {
        "enabled": True,
        "units_left": 0.0,
        "avg_cost": 0.0,
        "realized_pnl": 0.0,
    })


@dataclass
class Transaction:
    """交易记录"""
    id: Optional[int] = None
    fund_code: str = ""
    date: str = ""                              # YYYY-MM-DD
    tx_type: str = "BUY"                        # BUY / SELL
    amount: float = 0.0                         # 交易金额（元）
    units: float = 0.0                          # 份额
    nav: float = 0.0                            # 成交净值
    from_pool: bool = False                     # 是否从资金池出金
    note: str = ""


@dataclass
class DailyPlan:
    """每日/每周定投计划"""
    fund_code: str = ""
    date: str = ""                              # YYYY-MM-DD
    level: str = "mid"                          # low / mid / high
    dev_pct: float = 0.0                        # MA200 偏离度 (proxy_close - proxy_ma200) / proxy_ma200
    fixed_amount: float = 0.0                   # 固定定投金额
    dynamic_amount: float = 0.0                 # 动态定投金额
    total_amount: float = 0.0                   # 总定投金额
    reserve_before: float = 0.0                 # 准备金（使用前）
    reserve_after: float = 0.0                  # 准备金（使用后）
    strategy_mode: str = "ma200_deviation"      # 策略模式
    grid_pos: Optional[float] = None            # 网格位置（实验性，不用于生产）
    risk_guard_passed: bool = True              # 风险防护是否通过
    risk_guard_msg: str = ""                    # 风险防护消息


@dataclass
class PoolLedger:
    """资金池流水"""
    id: Optional[int] = None
    date: str = ""                              # YYYY-MM-DD
    fund_code: str = ""
    ledger_type: str = "DEPOSIT"                # DEPOSIT / BUY / REFUND / ADJUST
    amount: float = 0.0
    related_tx_id: Optional[int] = None
    note: str = ""


@dataclass
class FundState:
    """基金运行状态"""
    fund_code: str = ""
    reserve_balance: float = 0.0
    last_signal_date: Optional[str] = None
    last_low_trigger_date: Optional[str] = None
    updated_at: Optional[int] = None


@dataclass
class NavSnapshot:
    """净值快照"""
    fund_code: str = ""
    date: str = ""
    nav: float = 0.0
    source: str = ""
    is_trusted: bool = True
    data_date: Optional[str] = None


@dataclass
class MarketSnapshot:
    """市场数据快照（代理指数）"""
    fund_code: str = ""
    date: str = ""
    proxy_close: float = 0.0
    ma200: float = 0.0
    dev_pct: float = 0.0                # (proxy_close - ma200) / ma200
    source: str = ""
    is_trusted: bool = True
    data_date: Optional[str] = None
