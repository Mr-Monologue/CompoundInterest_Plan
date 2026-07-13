from typing import Optional
from sqlmodel import Field, SQLModel
from sqlalchemy import UniqueConstraint
from datetime import datetime


# 1. 资产表
class Asset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    type: str = "ETF"
    max_weight_limit: float = Field(default=0.2)
    # v2.1: Product Core fields
    role: str = "core"
    proxy_code: Optional[str] = None
    proxy_type: str = "INDEX"
    theme: str = ""
    target_weight: float = 0.0
    investment_thesis: str = ""
    expected_holding_months: int = 12
    review_cycle: str = "quarterly"
    invalidation_conditions: str = ""
    enabled: bool = True


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


# ── v0.8: Value-DCA Strategy Framework ────────────

# Asset role in portfolio
class AssetRole:
    CORE = "core"            # 核心仓位（宽基指数/优质混合）
    SATELLITE = "satellite"   # 卫星仓位（行业/主题）
    CASH = "cash"             # 现金等价
    WATCH_ONLY = "watch_only" # 仅观察

# Investment thesis status
class ThesisStatus:
    HOLD_OK = "HOLD_OK"              # 逻辑成立，继续持有
    WATCH = "WATCH"                  # 出现疑问，加强观察
    STOP_ADD = "STOP_ADD"            # 不再新增仓位
    REVIEW_REQUIRED = "REVIEW_REQUIRED"  # 需要重新评估

# Valuation state (PE/PB percentile — to be plugged in later)
class ValuationState:
    CHEAP = "cheap"              # 低估
    FAIR_LOW = "fair_low"        # 合理偏低
    FAIR = "fair"                # 合理
    FAIR_HIGH = "fair_high"      # 合理偏高
    EXPENSIVE = "expensive"      # 偏高
    UNKNOWN = "unknown"          # 未接入估值层

# Price position state (from MA200 dev_pct)
class PricePosition:
    LOW = "low_position"          # dev_pct ≤ -10%
    NORMAL = "normal_position"    # -10% < dev_pct ≤ +5%
    HIGH = "high_position"        # dev_pct > +5%

# 4% DCA rule state
class FourPercentState:
    DISABLED = "disabled"                # 未启用
    NOT_STARTED = "not_started"          # 等待首次
    WAITING_TRIGGER = "waiting_trigger"  # 等待触发
    TRIGGERED = "triggered"              # 已触发
    TRANCHES_EXHAUSTED = "tranches_exhausted"  # 份额耗尽
    DISABLED_BY_VALUATION = "disabled_by_valuation"
    DISABLED_BY_QUALITY = "disabled_by_quality"

# ── Price position helper ─────────────────────────

def classify_price_position(dev_pct: float) -> str:
    if dev_pct <= -0.10:
        return PricePosition.LOW
    elif dev_pct <= 0.05:
        return PricePosition.NORMAL
    else:
        return PricePosition.HIGH


# ── v0.8.2 Daily Decision + User Decision ──────────

class DailyDecision(SQLModel, table=True):
    """每日操作计划 — 由 Scheduler 自动生成，周/月复盘数据源"""
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str = Field(index=True)
    fund_code: str = Field(index=True)
    fund_name: str = ""

    # Decision fields
    system_status: str = "PASS"         # PASS/BLOCKED/WAITING/ANOMALY
    strategy_action: str = "fixed_dca"  # fixed_dca/dynamic_dca/observe/stop_dynamic/take_profit_watch/review_required
    recommended_amount: Optional[float] = None
    amount_permission: str = "hide_amount"  # show_recommended_amount/hide_amount/audit_only
    reason_summary: str = ""
    risk_reasons: str = ""

    # Signal state
    signal_ready: bool = False
    nav_ready: bool = False
    valuation_state: str = "unknown"
    price_position: str = "normal_position"
    four_percent_state: str = "disabled"
    risk_guard_passed: bool = True
    source: str = ""
    trusted: bool = True

    # Audit
    calculation_trace: str = ""  # JSON string
    created_by: str = "scheduler"
    decision_source: str = "scheduler"           # scheduler/manual/exposure_demo
    created_at: datetime = Field(default_factory=datetime.now)

    # v0.8.3 Exposure guard
    candidate_amount: Optional[float] = None    # original strategy amount
    final_amount: Optional[float] = None        # after exposure guard
    amount_source: str = "strategy"             # strategy / exposure_guard / cap
    exposure_status: str = "PASS"               # PASS / WATCH / REVIEW_REQUIRED / BLOCKED
    exposure_reasons: str = ""
    theme_bucket: str = "未分类"
    downgraded_from_action: str = ""            # original action before downgrade
    downgrade_reason: str = ""
    downgrade_from_fund: str = ""               # which fund caused downgrade
    candidate_action: str = ""                  # original candidate action
    final_action: str = ""                      # final action after guard
    exposure_guard_applied: bool = False        # was guard applied?
    industry_exposure_before: str = ""          # JSON: {industry: pct}
    classification_source: str = ""             # AKShare/manual/fallback
    classification_confidence: str = ""         # high/medium/low
    holding_date: str = ""                      # 持仓报告日期
    stale_holdings_warning: bool = False        # >120天未更新


class UserDecision(SQLModel, table=True):
    """用户对每日操作计划的执行记录"""
    id: Optional[int] = Field(default=None, primary_key=True)
    daily_decision_id: Optional[int] = Field(default=None, foreign_key="dailydecision.id")
    user_action: str = "pending"    # pending/acknowledged/executed/skipped
    actual_amount: Optional[float] = None
    actual_transaction_id: Optional[int] = None
    skip_reason: str = ""
    user_note: str = ""
    review_note: str = ""
    override_reason: str = ""
    confirmed_at: Optional[datetime] = None
    # v0.8.4: override exposure guard
    override_exposure_guard: bool = False
    override_reason: str = ""


# ── v1.0 AI Exposure Analyst models ──────────────────

class FundHoldingSnapshot(SQLModel, table=True):
    __tablename__ = "fund_holding_snapshot"
    id: Optional[int] = Field(default=None, primary_key=True)
    fund_code: str
    report_period: str = ""
    holding_date: str = ""
    source: str = "local_rule"
    top10_json: str = "[]"
    industry_distribution_json: str = "{}"
    updated_at: datetime = Field(default_factory=datetime.now)
    # v1.1.4 Coverage
    holding_count: int = 0
    holding_coverage_level: str = "unknown"
    stock_weight_coverage: float = 0.0
    coverage_source: str = ""


class FundExposureAnalysis(SQLModel, table=True):
    __tablename__ = "fund_exposure_analysis"
    id: Optional[int] = Field(default=None, primary_key=True)
    fund_code: str
    report_period: str = ""
    primary_theme: str = ""
    secondary_themes_json: str = "[]"
    theme_bucket: str = ""
    classification_source: str = "local_rule"
    classification_confidence: str = "low"
    evidence_json: str = "[]"
    uncertainty_json: str = "[]"
    model_name: str = ""
    model_version: str = ""
    prompt_hash: str = ""
    input_hash: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


class FundOverlap(SQLModel, table=True):
    __tablename__ = "fund_overlap"
    id: Optional[int] = Field(default=None, primary_key=True)
    fund_code_a: str
    fund_code_b: str
    report_period: str = ""
    top10_overlap_score: float = 0.0
    industry_overlap_score: float = 0.0
    theme_overlap_score: float = 0.0
    overlap_level: str = "low"
    evidence_json: str = "[]"


# v1.9 DataQualityIssue model
class DataQualityIssue(SQLModel, table=True):
    __tablename__ = "data_quality_issue"
    id: Optional[int] = Field(default=None, primary_key=True)
    issue_type: str = ""
    related_fund_code: str = ""
    related_module: str = ""
    severity: str = "info"
    priority: str = "P3"
    status: str = "OPEN"
    source: str = ""
    evidence_json: str = "{}"
    suggested_fix: str = ""
    fix_attempt_count: int = 0
    last_fix_result: str = ""
    audit_log_json: str = "[]"
    first_seen_at: datetime = Field(default_factory=datetime.now)
    last_seen_at: datetime = Field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None


# v2.1: Weekly Plan models

class InvestmentPlanConfig(SQLModel, table=True):
    __tablename__ = "investment_plan_config"
    __table_args__ = {"extend_existing": True}
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = "default"
    weekly_budget: float = 200.0
    core_target_ratio: float = 0.65
    satellite_target_ratio: float = 0.35
    reserve_balance: float = 0.0
    strategy_version: str = "v2.1"
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class WeeklyInvestmentPlan(SQLModel, table=True):
    __tablename__ = "weekly_investment_plan"
    __table_args__ = (UniqueConstraint("week_start", "config_id", name="uq_weekly_plan_week_config"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    week_start: str = ""
    week_end: str = ""
    config_id: int = 0
    strategy_version: str = "v2.1"
    status: str = "DRAFT"
    available_budget: float = 0.0
    core_budget: float = 0.0
    satellite_budget: float = 0.0
    total_candidate_amount: float = 0.0
    total_final_amount: float = 0.0
    unallocated_core_budget: float = 0.0
    unallocated_satellite_budget: float = 0.0
    blocked_item_count: int = 0
    review_required_item_count: int = 0
    data_quality_status: str = "unknown"
    exposure_status: str = "unknown"
    created_at: datetime = Field(default_factory=datetime.now)
    frozen_at: Optional[datetime] = None


class WeeklyPlanItem(SQLModel, table=True):
    __tablename__ = "weekly_plan_item"
    __table_args__ = (UniqueConstraint("weekly_plan_id", "daily_decision_id", name="uq_weekly_plan_decision"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    weekly_plan_id: int = 0
    asset_code: str = ""
    asset_role: str = "core"
    daily_decision_id: Optional[int] = None
    fixed_amount: Optional[float] = None
    dynamic_amount: Optional[float] = None
    candidate_amount: Optional[float] = None
    final_amount: Optional[float] = None
    action: str = "NO_ACTION"
    valuation_state: str = "unknown"
    risk_status: str = "ok"
    data_quality_status: str = "unknown"
    reason_summary: str = ""
    calculation_trace: str = "{}"
    created_at: datetime = Field(default_factory=datetime.now)


class DecisionJournalEntry(SQLModel, table=True):
    __tablename__ = "decision_journal_entry"
    id: Optional[int] = Field(default=None, primary_key=True)
    weekly_plan_item_id: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.now)
    investment_thesis_snapshot: str = ""
    expected_scenario: str = ""
    invalidation_conditions: str = ""
    known_unknowns: str = ""
    user_note: str = ""
    immutable: bool = True
