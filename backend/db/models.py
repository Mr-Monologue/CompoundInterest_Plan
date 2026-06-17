from typing import Optional
from sqlmodel import Field, SQLModel
from datetime import datetime


# 1. 资产表
class Asset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    type: str = "ETF"
    max_weight_limit: float = Field(default=0.2)


# 2. 交易表
class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    asset_code: str = Field(index=True)
    date: datetime = Field(default_factory=datetime.now)
    type: str
    price: float
    amount: float
    fee: float = 0.0
    units: float


# 3. FundState
class FundState(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    asset_code: str = Field(index=True, unique=True)
    cumulative_reserve_usage: float = 0.0
    last_signal_date: Optional[str] = Field(default=None, nullable=True)
    updated_at: datetime = Field(default_factory=datetime.now)


# 4. DailyPlan — 每日定投计划
class DailyPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    asset_code: str = Field(index=True)
    date: str = Field(index=True)

    # 行情
    close: float
    ma200: float
    dev_pct: float       # 真实 MA200 偏离: (close - ma200) / ma200
    grid_pos: float = 0.0  # 网格位置（实验模式，不用于生产）

    # 策略结果
    level: str            # low/mid/high — 由 classify_dev_pct(dev_pct) 计算
    base_amt: float
    dyn_amt: float
    total_amt: float

    # 状态快照
    reserve_before: float
    reserve_after: float

    # 审计追踪
    created_by: str = "scheduler"
    idempotency_key: Optional[str] = Field(default=None, unique=True)


# 5. PlanState
class PlanState(SQLModel, table=True):
    id: Optional[int] = Field(default=1, primary_key=True)
    pool_balance: float = 0.0
    base_investment: float = 200.0
    deposit_frequency: str = "MANUAL"
    auto_deposit_amount: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.now)


# 6. Stock / FundHolding / IndustryLimit
class Stock(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    industry: str = "未分类"
    updated_at: datetime = Field(default_factory=datetime.now)


class FundHolding(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    fund_code: str = Field(index=True)
    stock_code: str = Field(index=True)
    stock_name: str
    weight: float
    report_date: str


class IndustryLimit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    industry: str = Field(index=True, unique=True)
    max_weight: float = 0.4


# ── classify_dev_pct: 唯一权威入口 ──────────────

def classify_dev_pct(dev_pct: float) -> str:
    """low: ≤-10% | mid: -10%~+5% | high: >+5%"""
    if dev_pct <= -0.10:
        return "low"
    elif dev_pct <= 0.05:
        return "mid"
    else:
        return "high"
