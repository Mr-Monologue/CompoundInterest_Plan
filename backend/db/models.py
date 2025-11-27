from typing import Optional
from sqlmodel import Field, SQLModel
from datetime import datetime


# 1. 资产表：存储你关注的基金/股票
class Asset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)  # 代码，如 "sh000300"
    name: str  # 名称，如 "沪深300"
    type: str = "ETF"  # 类型


# 2. 交易表：存储你的买卖记录
class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    asset_code: str = Field(index=True)  # 关联哪个资产
    date: datetime = Field(default_factory=datetime.now)
    type: str  # "BUY" or "SELL"
    price: float  # 成交价
    amount: float  # 成交金额（总金额，包含手续费）
    fee: float = 0.0  # 手续费
    units: float  # 成交份额 (净金额/价格)


# === ⬇️ 新增：策略引擎专用表 ⬇️ ===


# === ⬇️ 修改：FundState (单标的状态) ⬇️ ===
# 我们不再依赖这里的 reserve_balance 做决策，但可以保留它记录"该基金累计贡献/消耗了多少储备"
class FundState(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    asset_code: str = Field(index=True, unique=True)
    # ⚠️ 注意：这个字段现在的含义变了 -> "历史累计从总池子里拿走的净额" (正数=拿走，负数=贡献)
    cumulative_reserve_usage: float = 0.0
    last_signal_date: Optional[str] = Field(default=None, nullable=True)
    updated_at: datetime = Field(default_factory=datetime.now)


# 2. 每日定投计划表 (历史记录)
# 记录每一天系统建议你做什么，用于生成周报/复盘
class DailyPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    asset_code: str = Field(index=True)
    date: str = Field(index=True)  # YYYY-MM-DD

    # 核心行情
    close: float  # 当日收盘价
    ma200: float  # 当日年线
    dev_pct: float  # 偏离度 (小数，如 -0.15)

    # 策略结果
    level: str  # low (低估), mid (合理), high (高估)
    base_amt: float  # 固定投入金额
    dyn_amt: float  # 动态投入金额 (来自准备金)
    total_amt: float  # 总建议投入

    # 状态快照 (用于回溯)
    reserve_before: float
    reserve_after: float


# === ⬇️ 新增：全局投资计划表 (PlanState) ⬇️ ===
# 这张表永远只会有一行数据，ID=1
class PlanState(SQLModel, table=True):
    id: Optional[int] = Field(default=1, primary_key=True)

    weekly_budget: float = 200.0  # 每周基础预算 (例如 200)
    global_reserve: float = 0.0  # 💰 全局准备金池 (所有基金共享)

    current_week_start: str = None  # 本周起始日 (用于判断是否跨周重置)
    budget_used_this_week: float = 0.0  # 本周已使用的预算 (0 ~ 200)

    updated_at: datetime = Field(default_factory=datetime.now)
