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
    amount: float  # 成交金额
    units: float  # 成交份额 (金额/价格)


# === ⬇️ 新增：策略引擎专用表 ⬇️ ===


# 1. 基金状态表 (存钱罐)
# 记录每个基金当前的准备金余额，以及上次更新的时间
class FundState(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    asset_code: str = Field(index=True, unique=True)  # 关联基金代码

    reserve_balance: float = 0.0  # 准备金余额

    # === 新增字段 ===
    year_invested: float = 0.0  # 本年度已投入金额 (用于控年度上限)
    max_year_quota: float = 12000.0  # 年度最大预算 (默认1.2万，可改)
    last_buy_date: Optional[str] = Field(
        default=None, nullable=True
    )  # 上次发生"买入"的日期 (用于90天扫入)

    last_signal_date: Optional[str] = Field(
        default=None, nullable=True
    )  # 上次产生信号的日期 (YYYY-MM-DD)
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
