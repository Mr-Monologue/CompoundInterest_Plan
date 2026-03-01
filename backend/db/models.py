from typing import Optional
from sqlmodel import Field, SQLModel
from datetime import datetime


# 1. 资产表：存储你关注的基金/股票
class Asset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)  # 代码，如 "sh000300"
    name: str  # 名称，如 "沪深300"
    type: str = "ETF"  # 类型

    # 🔥 新增：单资产最大持仓占比限制 (0.0 ~ 1.0)
    # 默认给 0.2 (20%)，防止单吊
    max_weight_limit: float = Field(default=0.2)


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


# === ⬇️ 修改：全局计划表 (PlanState) ⬇️ ===
class PlanState(SQLModel, table=True):
    id: Optional[int] = Field(default=1, primary_key=True)

    # 1. 资金池 (实体账户)
    pool_balance: float = 0.0  # 💰 当前账户里的可用现金 (可用于投资的钱)

    # 2. 策略配置 (规则)
    base_investment: float = (
        200.0  # 🎯 定投基准额度 (用于计算网格倍数的基础单位，比如 Z=0 时投多少)
    )

    # 3. 自动充值规则 (可选，预留字段)
    deposit_frequency: str = "MANUAL"  # MANUAL(手动), WEEKLY(每周), MONTHLY(每月)
    auto_deposit_amount: float = 0.0  # 自动充值金额

    updated_at: datetime = Field(default_factory=datetime.now)


# === ⬇️ 新增：穿透式风控专用表 ⬇️ ===


class Stock(SQLModel, table=True):
    """单只股票信息（含行业）"""

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)  # 如 600519
    name: str
    industry: str = "未分类"  # 申万一级行业
    updated_at: datetime = Field(default_factory=datetime.now)


class FundHolding(SQLModel, table=True):
    """基金持仓明细"""

    id: Optional[int] = Field(default=None, primary_key=True)
    fund_code: str = Field(index=True)  # 对应 Asset.code
    stock_code: str = Field(index=True)  # 对应 Stock.code
    stock_name: str
    weight: float  # 持仓占比，0.0~1.0
    report_date: str  # 报告期，如 '2024-09-30'


class IndustryLimit(SQLModel, table=True):
    """行业级刹车上限配置"""

    id: Optional[int] = Field(default=None, primary_key=True)
    industry: str = Field(index=True, unique=True)  # 行业名称
    max_weight: float = 0.4  # 0.0~1.0，默认40%
