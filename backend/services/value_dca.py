"""value_dca.py — v0.8 Value-DCA Strategy Framework

4% 定投法实验模块（默认 dry_run，不进入实盘金额）。
决策分层: 数据层→资产层→估值层→价格层→4%触发层→资金层→风控层.
"""
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class DecisionLayer:
    layer_name: str
    status: str
    score: float = 1.0
    reason: str = ""
    blocking: bool = False


@dataclass
class DecisionReport:
    fund_code: str = ""
    fund_name: str = ""
    asset_role: str = "satellite"
    signal_ready: bool = False
    nav_ready: bool = False

    # Layers
    data_layer: Optional[DecisionLayer] = None
    thesis_layer: Optional[DecisionLayer] = None
    valuation_layer: Optional[DecisionLayer] = None
    price_layer: Optional[DecisionLayer] = None
    four_percent_layer: Optional[DecisionLayer] = None
    amount_layer: Optional[DecisionLayer] = None
    risk_layer: Optional[DecisionLayer] = None

    # Outputs
    recommended_amount: Optional[float] = None
    computed_amount: Optional[float] = None
    calculation_trace: Dict[str, Any] = field(default_factory=dict)

    # Review
    decision_reason: str = ""
    review_required: bool = False
    review_reason: str = ""


def evaluate_data_layer(nav, proxy_close, ma200, source: str) -> DecisionLayer:
    if source.lower() == "mock":
        return DecisionLayer("数据层", "BLOCKED", 0, "Mock数据源", blocking=True)
    if proxy_close is None or ma200 is None or ma200 <= 0:
        return DecisionLayer("数据层", "BLOCKED", 0, "代理指数数据缺失", blocking=True)
    return DecisionLayer("数据层", "READY", 1.0, "数据完整")


def evaluate_thesis_layer(role: str, thesis: str) -> DecisionLayer:
    if thesis == "REVIEW_REQUIRED":
        return DecisionLayer("资产层", "REVIEW", 0.5, "投资逻辑需复核", blocking=True)
    if thesis == "STOP_ADD":
        return DecisionLayer("资产层", "STOP", 0.3, "已暂停加仓", blocking=True)
    return DecisionLayer("资产层", f"HOLD ({role})", 1.0, "逻辑成立")


def evaluate_valuation_layer() -> DecisionLayer:
    """估值层 — v0.8 暂未接入 PE/PB 分位"""
    return DecisionLayer("估值层", "unknown", 0.5, "PE/PB分位待接入（不阻断当前策略）", blocking=False)


def evaluate_price_layer(dev_pct: float) -> DecisionLayer:
    from db.models import classify_price_position, PricePosition
    pos = classify_price_position(dev_pct)
    labels = {PricePosition.LOW: "低估区间", PricePosition.NORMAL: "正常区间", PricePosition.HIGH: "偏高区间"}
    # Price position never blocks — it informs amount, not action
    return DecisionLayer("价格层", pos, 1.0, f"MA200偏离 {dev_pct*100:+.2f}% — {labels.get(pos, pos)}", blocking=False)


def evaluate_four_percent_layer(
    proxy_close: float,
    last_buy_ref: Optional[float],
    tranches_used: int,
    tranches_total: int,
    valuation_state: str,
) -> DecisionLayer:
    """4% 定投法触发层（dry_run）"""
    from db.models import FourPercentState

    # Valuation gate: only cheap or fair_low
    if valuation_state not in ("cheap", "fair_low", "unknown"):
        return DecisionLayer(
            "4%触发层", FourPercentState.DISABLED_BY_VALUATION, 0,
            f"估值状态={valuation_state}，不满足4%法前提", blocking=False
        )

    if tranches_used >= tranches_total:
        return DecisionLayer(
            "4%触发层", FourPercentState.TRANCHES_EXHAUSTED, 0,
            f"已用 {tranches_used}/{tranches_total} 份", blocking=False
        )

    if last_buy_ref is None or last_buy_ref <= 0:
        return DecisionLayer(
            "4%触发层", FourPercentState.NOT_STARTED, 0,
            "尚未建立参考价", blocking=False
        )

    trigger = last_buy_ref * 0.96
    if proxy_close <= trigger:
        next_trigger = proxy_close * 0.96
        return DecisionLayer(
            "4%触发层", FourPercentState.TRIGGERED, 0.2,
            f"触发! proxy_close={proxy_close:.2f} ≤ trigger={trigger:.2f}，下一触发={next_trigger:.2f}",
            blocking=False
        )
    else:
        return DecisionLayer(
            "4%触发层", FourPercentState.WAITING_TRIGGER, 0,
            f"未触发: proxy_close={proxy_close:.2f} > trigger={trigger:.2f}",
            blocking=False
        )


def evaluate_risk_layer(action_allowed: bool, errors: list) -> DecisionLayer:
    if not action_allowed:
        return DecisionLayer("风控层", "BLOCKED", 0, "; ".join(errors), blocking=True)
    return DecisionLayer("风控层", "PASS", 1.0, "风险检查通过", blocking=False)


def build_decision_report(
    fund_code: str, fund_name: str,
    source: str, nav, proxy_close, ma200, dev_pct: float,
    role: str, thesis: str,
    last_buy_ref: Optional[float], tranches_used: int, tranches_total: int,
    valuation_state: str, risk_passed: bool, risk_errors: list,
    computed_amount: float, action_allowed: bool,
) -> DecisionReport:
    """Build full layered decision report."""

    # Evaluate each layer
    data = evaluate_data_layer(nav, proxy_close, ma200, source)
    th = evaluate_thesis_layer(role, thesis)
    val = evaluate_valuation_layer()
    price = evaluate_price_layer(dev_pct)
    fp = evaluate_four_percent_layer(
        proxy_close or 0, last_buy_ref, tranches_used, tranches_total, valuation_state
    )
    risk = evaluate_risk_layer(risk_passed, risk_errors)

    # Amount policy
    amount_status = "PASS" if action_allowed else "BLOCKED"
    amount = DecisionLayer(
        "资金层", amount_status, 1.0 if action_allowed else 0,
        f"计算金额={computed_amount:.2f}" if action_allowed else "阻止输出金额"
    )

    blocking_layers = [l for l in [data, th, risk] if l.blocking]
    rec = computed_amount if action_allowed and not blocking_layers else None

    return DecisionReport(
        fund_code=fund_code, fund_name=fund_name, asset_role=role,
        signal_ready=data.status == "READY", nav_ready=True,
        data_layer=data, thesis_layer=th, valuation_layer=val,
        price_layer=price, four_percent_layer=fp,
        amount_layer=amount, risk_layer=risk,
        recommended_amount=rec, computed_amount=computed_amount,
        calculation_trace={
            "dev_pct": dev_pct, "proxy_close": proxy_close, "ma200": ma200,
            "computed_amount": computed_amount,
            "four_percent_dry_run": {
                "state": fp.status, "last_buy_ref": last_buy_ref,
                "tranches_used": tranches_used, "tranches_total": tranches_total,
            }
        },
        decision_reason=f"价格层={price.status}, 风控={risk.status}, 金额={rec or 'BLOCKED'}",
        review_required=any(l.blocking for l in [data, th, risk]),
        review_reason="; ".join(l.reason for l in blocking_layers) if blocking_layers else "",
    )


def build_framework_response(report: DecisionReport) -> dict:
    """Convert DecisionReport to API JSON response."""
    def _layer(l: Optional[DecisionLayer]) -> dict:
        if l is None: return {}
        return {"name": l.layer_name, "status": l.status, "score": l.score, "reason": l.reason, "blocking": l.blocking}

    return {
        "fund_code": report.fund_code,
        "fund_name": report.fund_name,
        "asset_role": report.asset_role,
        "signal_ready": report.signal_ready,
        "layers": {
            "data": _layer(report.data_layer),
            "thesis": _layer(report.thesis_layer),
            "valuation": _layer(report.valuation_layer),
            "price": _layer(report.price_layer),
            "four_percent": _layer(report.four_percent_layer),
            "amount": _layer(report.amount_layer),
            "risk": _layer(report.risk_layer),
        },
        "recommended_amount": report.recommended_amount,
        "computed_amount": report.computed_amount,
        "calculation_trace": report.calculation_trace,
        "decision_reason": report.decision_reason,
        "review_required": report.review_required,
        "review_reason": report.review_reason,
    }
