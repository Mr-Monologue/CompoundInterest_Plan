"""
SmartInvest 数据层
- SQLModel 全部模型定义
- SQLite 引擎 + 建表迁移
- Session 工厂 + 全局状态读取
"""

import os
from typing import Optional
from datetime import datetime

from sqlmodel import Field, SQLModel, Session, select, create_engine

# =============================================
#  数据模型
# =============================================


class Asset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    type: str = "ETF"
    max_weight_limit: float = Field(default=0.2)


class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    asset_code: str = Field(index=True)
    date: datetime = Field(default_factory=datetime.now)
    type: str
    price: float
    amount: float
    fee: float = 0.0
    units: float


class FundState(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    asset_code: str = Field(index=True, unique=True)
    cumulative_reserve_usage: float = 0.0
    last_signal_date: Optional[str] = Field(default=None, nullable=True)
    updated_at: datetime = Field(default_factory=datetime.now)


class DailyPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    asset_code: str = Field(index=True)
    date: str = Field(index=True)
    close: float
    ma200: float
    dev_pct: float       # REAL MA200 deviation: (close - ma200) / ma200
    grid_pos: float = 0.0  # Grid position for grid strategy (experimental)
    level: str            # low / mid / high — computed by classify_dev_pct(dev_pct)
    base_amt: float
    dyn_amt: float
    total_amt: float
    reserve_before: float
    reserve_after: float
    created_by: str = "scheduler"
    idempotency_key: Optional[str] = Field(default=None, unique=True)


class PlanState(SQLModel, table=True):
    id: Optional[int] = Field(default=1, primary_key=True)
    pool_balance: float = 0.0
    base_investment: float = 200.0
    deposit_frequency: str = "MANUAL"
    auto_deposit_amount: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.now)


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


# =============================================
#  数据库引擎 + 建表
# =============================================

DB_PATH = os.environ.get("SMARTINVEST_DB", "invest.db")
engine = create_engine(f"sqlite:///{DB_PATH}")


def create_db_and_tables():
    if os.path.exists(DB_PATH):
        from sqlalchemy import inspect, text
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        # Add missing columns — never DROP TABLE
        if "dailyplan" in tables:
            cols = [c["name"] for c in inspector.get_columns("dailyplan")]
            with engine.connect() as conn:
                if "grid_pos" not in cols:
                    conn.execute(text('ALTER TABLE dailyplan ADD COLUMN grid_pos FLOAT DEFAULT 0.0'))
                if "created_by" not in cols:
                    conn.execute(text("ALTER TABLE dailyplan ADD COLUMN created_by TEXT DEFAULT 'scheduler'"))
                if "idempotency_key" not in cols:
                    conn.execute(text("ALTER TABLE dailyplan ADD COLUMN idempotency_key TEXT"))
                conn.commit()

    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


def get_global_state(session: Session) -> PlanState:
    state = session.exec(select(PlanState).where(PlanState.id == 1)).first()
    if not state:
        state = PlanState(id=1, pool_balance=0.0, base_investment=200.0, deposit_frequency="MANUAL")
        session.add(state)
        session.commit()
        session.refresh(state)
    return state


# ── Strategy utility: canonical dev_pct → level ──────

def classify_dev_pct(dev_pct: float) -> str:
    """Canonical MA200 deviation → level. Single source of truth.
    low: ≤ -10% | mid: -10%~+5% | high: > +5%
    dev_pct=0.0033 (0.33%) → mid, NOT low.
    """
    if dev_pct <= -0.10:
        return "low"
    elif dev_pct <= 0.05:
        return "mid"
    else:
        return "high"
