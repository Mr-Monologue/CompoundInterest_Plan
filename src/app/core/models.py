#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据模型定义 — v2.0 实盘辅助统一入口

新增字段（v2.0）：
    - created_by:   "hermes" | "gui" | "scheduler" | "manual"
    - idempotency_key: 防重复写入
    - calculation_trace: 审计链（JSON）
    - confirmed: Hermes 写入前需确认
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any


@dataclass
class Asset:
    """基金/资产定义"""
    fund_code: str
    fund_name: str
    fund_name_en: str = ""
    proxy_code: Optional[str] = None
    proxy_type: str = "INDEX"
    proxy_index_en: str = ""
    weekly_budget: float = 200.0
    manual_holdings: dict = field(default_factory=lambda: {
        "enabled": True, "units_left": 0.0, "avg_cost": 0.0, "realized_pnl": 0.0,
    })


@dataclass
class Transaction:
    """交易记录"""
    id: Optional[int] = None
    fund_code: str = ""
    date: str = ""
    tx_type: str = "BUY"
    amount: float = 0.0
    units: float = 0.0
    nav: float = 0.0
    from_pool: bool = False
    note: str = ""
    created_by: str = "manual"                  # hermes | gui | scheduler | manual
    idempotency_key: Optional[str] = None       # tx:{code}:{date}:{type}:{amount}:{hash}
    confirmed: bool = False                     # Hermes 写入前必须确认


@dataclass
class DailyPlan:
    """每日/每周定投计划"""
    fund_code: str = ""
    date: str = ""
    level: str = "mid"
    dev_pct: float = 0.0                        # MA200 偏离度
    fixed_amount: float = 0.0
    dynamic_amount: float = 0.0
    total_amount: float = 0.0
    reserve_before: float = 0.0
    reserve_after: float = 0.0
    strategy_mode: str = "ma200_deviation"
    grid_pos: Optional[float] = None
    risk_guard_passed: bool = True
    risk_guard_msg: str = ""
    created_by: str = "scheduler"               # hermes | gui | scheduler
    idempotency_key: Optional[str] = None       # daily_sample:{code}:{date}
    calculation_trace: Optional[Dict[str, Any]] = None  # 审计链


@dataclass
class PoolLedgerEntry:
    """资金池流水"""
    id: Optional[int] = None
    date: str = ""
    fund_code: str = ""
    entry_type: str = "DEPOSIT"
    amount: float = 0.0
    related_tx_id: Optional[int] = None
    note: str = ""
    created_by: str = "manual"
    idempotency_key: Optional[str] = None


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
    created_by: str = "scheduler"


@dataclass
class MarketSnapshot:
    """市场数据快照（代理指数）"""
    fund_code: str = ""
    date: str = ""
    proxy_close: float = 0.0
    ma200: float = 0.0
    dev_pct: float = 0.0
    source: str = ""
    is_trusted: bool = True
    data_date: Optional[str] = None
    created_by: str = "scheduler"


# ── idempotency_key 生成 ───────────────────────────

def make_sample_idempotency_key(fund_code: str, date_str: str) -> str:
    """每日采样幂等键"""
    return f"daily_sample:{fund_code}:{date_str}"


def make_tx_idempotency_key(
    fund_code: str, date_str: str, tx_type: str, amount: float, ref: str = ""
) -> str:
    """交易录入幂等键"""
    import hashlib
    raw = f"{fund_code}:{date_str}:{tx_type}:{amount:.2f}:{ref}"
    h = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"tx:{fund_code}:{date_str}:{tx_type}:{amount:.2f}:{h}"


def make_pool_idempotency_key(
    fund_code: str, date_str: str, entry_type: str, amount: float
) -> str:
    """资金池流水幂等键"""
    import hashlib
    raw = f"pool:{fund_code}:{date_str}:{entry_type}:{amount:.2f}"
    h = hashlib.md5(raw.encode()).hexdigest()[:8]
    return f"pool:{fund_code}:{date_str}:{entry_type}:{amount:.2f}:{h}"
