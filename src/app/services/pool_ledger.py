#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金池账务模块

管理准备金池的流入/流出流水。
原则：
    - 资金池不能随意增减
    - from_pool BUY 必须余额充足，不足返回错误
    - 删除 from_pool BUY 必须退回资金池
    - 修改交易金额默认禁止（请删除后重记）

流水类型：
    DEPOSIT  — 每周流入
    BUY      — 从池中支出买入
    REFUND   — 删除交易退款
    ADJUST   — 人工调整（需审计记录）
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from datetime import date as DateType

# 量化精度
Q2 = Decimal("0.01")


def D(x) -> Decimal:
    if x is None:
        return Decimal("0")
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(x)


@dataclass
class PoolEntry:
    """资金池流水条目"""
    id: Optional[int] = None
    fund_code: str = ""
    date: str = ""
    entry_type: str = "DEPOSIT"  # DEPOSIT / BUY / REFUND / ADJUST
    amount: Decimal = Decimal("0")
    balance_after: Decimal = Decimal("0")
    related_tx_id: Optional[int] = None
    note: str = ""


class PoolLedger:
    """资金池账本"""

    def __init__(self, fund_code: str, initial_balance: float = 0.0):
        self.fund_code = fund_code
        self.balance = D(initial_balance)
        self.entries: list[PoolEntry] = []
        self._next_id = 1

    @property
    def current_balance(self) -> Decimal:
        return self.balance.quantize(Q2, rounding=ROUND_HALF_UP)

    # ── 存款 ──────────────────────────────────────────

    def deposit(self, amount: float, date: str = "", note: str = "") -> PoolEntry:
        """每周/周期性流入资金池"""
        amt = D(amount)
        if amt <= 0:
            raise ValueError(f"存款金额必须 > 0，当前: {amount}")

        self.balance += amt
        entry = PoolEntry(
            id=self._next_id,
            fund_code=self.fund_code,
            date=date,
            entry_type="DEPOSIT",
            amount=amt,
            balance_after=self.current_balance,
            note=note or "准备金流入",
        )
        self._next_id += 1
        self.entries.append(entry)
        return entry

    # ── 买入支出 ──────────────────────────────────────

    def buy(self, amount: float, date: str = "", note: str = "") -> PoolEntry:
        """从资金池支出（买入基金）"""
        amt = D(amount)
        if amt <= 0:
            raise ValueError(f"买入金额必须 > 0，当前: {amount}")

        if self.balance < amt:
            raise ValueError(
                f"资金池余额不足：需要 ¥{amt:.2f}，当前余额 ¥{self.balance:.2f}"
            )

        self.balance -= amt
        entry = PoolEntry(
            id=self._next_id,
            fund_code=self.fund_code,
            date=date,
            entry_type="BUY",
            amount=amt,
            balance_after=self.current_balance,
            note=note or "动态定投买入",
        )
        self._next_id += 1
        self.entries.append(entry)
        return entry

    # ── 退款（删除交易回滚） ────────────────────────────

    def refund(self, entry_id: int) -> PoolEntry:
        """退款：删除某笔 BUY 交易后，金额退回资金池"""
        target = None
        for e in self.entries:
            if e.id == entry_id and e.entry_type == "BUY":
                target = e
                break

        if target is None:
            raise ValueError(f"未找到可退款的 BUY 交易: id={entry_id}")

        if target.balance_after == Decimal("0"):
            raise ValueError(f"交易 id={entry_id} 已退款")

        self.balance += target.amount
        entry = PoolEntry(
            id=self._next_id,
            fund_code=self.fund_code,
            date=str(DateType.today()),
            entry_type="REFUND",
            amount=target.amount,
            balance_after=self.current_balance,
            related_tx_id=entry_id,
            note=f"删除交易 #{entry_id} 退款: {target.note}",
        )
        self._next_id += 1
        self.entries.append(entry)
        return entry

    # ── 调整 ──────────────────────────────────────────

    def adjust(self, amount: float, note: str) -> PoolEntry:
        """人工调整（必须注明原因）"""
        amt = D(amount)
        self.balance += amt

        entry = PoolEntry(
            id=self._next_id,
            fund_code=self.fund_code,
            date=str(DateType.today()),
            entry_type="ADJUST",
            amount=amt,
            balance_after=self.current_balance,
            note=f"人工调整: {note}",
        )
        self._next_id += 1
        self.entries.append(entry)
        return entry

    # ── 摘要 ──────────────────────────────────────────

    def summary(self) -> dict:
        """账本摘要"""
        deposits = sum(e.amount for e in self.entries if e.entry_type == "DEPOSIT")
        buys = sum(e.amount for e in self.entries if e.entry_type == "BUY")
        refunds = sum(e.amount for e in self.entries if e.entry_type == "REFUND")
        adjusts = sum(e.amount for e in self.entries if e.entry_type == "ADJUST")

        return {
            "fund_code": self.fund_code,
            "balance": float(self.current_balance),
            "total_deposits": float(deposits),
            "total_buys": float(buys),
            "total_refunds": float(refunds),
            "total_adjusts": float(adjusts),
            "entry_count": len(self.entries),
        }


# ── 数据库持久化（可选） ────────────────────────────────

POOL_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS pool_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_code TEXT NOT NULL,
    date TEXT NOT NULL,
    entry_type TEXT NOT NULL CHECK(entry_type IN ('DEPOSIT','BUY','REFUND','ADJUST')),
    amount REAL NOT NULL,
    balance_after REAL NOT NULL,
    related_tx_id INTEGER,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pool_ledger_fund_code ON pool_ledger(fund_code);
CREATE INDEX IF NOT EXISTS idx_pool_ledger_date ON pool_ledger(date);
CREATE INDEX IF NOT EXISTS idx_pool_ledger_type ON pool_ledger(entry_type);
"""


def init_pool_ledger_db(db_path: str = "data/trend.db"):
    """初始化资金池流水表（仅建表，不删数据）"""
    import sqlite3
    con = sqlite3.connect(db_path)
    try:
        con.executescript(POOL_LEDGER_DDL)
        con.commit()
        print("✓ pool_ledger 表初始化完成")
    finally:
        con.close()
