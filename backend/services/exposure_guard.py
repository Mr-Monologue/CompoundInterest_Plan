"""exposure_guard.py — v0.8.3 Portfolio Exposure Guard

Combined exposure check before final DailyDecision:
- Same theme bucket: max 1 actionable per week
- Industry exposure > 30%: stop dynamic
- Industry exposure > 40%: REVIEW_REQUIRED
- Top10 overlap > 50%: not both actionable
- Portfolio total > weekly_budget × 3: REVIEW_REQUIRED

Does NOT change single-fund strategy signals.
"""

from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

WEEKLY_BUDGET = 200.0
PORTFOLIO_CAP_MULTIPLIER = 3.0  # max total = weekly_budget × 3


# Theme bucket mapping (keyword → bucket)
THEME_BUCKETS = {
    "消费": "消费", "食品": "消费", "白酒": "消费", "饮料": "消费",
    "医药": "医药", "医疗": "医药",
    "科技": "科技", "信息": "科技", "电子": "科技", "半导体": "科技",
    "金融": "金融", "银行": "金融", "证券": "金融",
    "新能源": "新能源", "电池": "新能源",
    "军工": "军工",
    "文体": "文体",
    "制造": "制造",
    "混合": "混合", "价值": "价值", "蓝筹": "混合", "精选": "混合",
}


def classify_theme(fund_name: str) -> str:
    for kw, bucket in THEME_BUCKETS.items():
        if kw in fund_name:
            return bucket
    return "混合"


def get_industry_exposure(session) -> Dict[str, float]:
    """Get current portfolio industry exposure percentages."""
    from services.holdings import get_fund_industry_vector
    from db.models import Asset
    from sqlmodel import select as _sel

    assets = session.exec(_sel(Asset)).all()

    total_weight = 0.0
    industry_map = defaultdict(float)

    for asset in assets:
        vec = get_fund_industry_vector(session, asset.code)
        if vec:
            for ind, w in vec.items():
                industry_map[ind] += w
                total_weight += w

    if total_weight == 0:
        return {}

    return {ind: w / total_weight for ind, w in industry_map.items()}


def get_fund_top_holdings(session, fund_code: str) -> List[str]:
    """Get top 10 stock codes for a fund."""
    from sqlmodel import select as _sel
    from db.models import FundHolding
    holdings = session.exec(
        _sel(FundHolding).where(FundHolding.fund_code == fund_code).order_by(FundHolding.weight.desc()).limit(10)
    ).all()
    return [h.stock_code for h in holdings]


def calculate_overlap(stocks_a: List[str], stocks_b: List[str]) -> float:
    """Jaccard overlap of top holdings."""
    if not stocks_a or not stocks_b:
        return 0.0
    set_a, set_b = set(stocks_a), set(stocks_b)
    return len(set_a & set_b) / min(len(set_a), len(set_b))


def apply_exposure_guard(
    candidates: List[Dict[str, Any]],
    session,
) -> List[Dict[str, Any]]:
    """
    Apply portfolio exposure guard to candidate decisions.

    Each candidate is a dict with:
        fund_code, fund_name, strategy_action, recommended_amount,
        system_status, dev_pct, grid_pos

    Returns: list with potentially downgraded decisions.
    """
    if len(candidates) <= 1:
        return candidates

    industry_exposure = get_industry_exposure(session)

    # 1. Theme bucket: max 1 actionable per bucket
    by_theme = defaultdict(list)
    for c in candidates:
        theme = classify_theme(c.get("fund_name", ""))
        c["theme_bucket"] = theme
        if c["strategy_action"] in ("fixed_dca", "dynamic_dca", "buy") and c["system_status"] == "PASS":
            by_theme[theme].append(c)

    for theme, items in by_theme.items():
        if len(items) > 1:
            # Sort by priority: core > satellite, lower dev_pct > higher
            items.sort(key=lambda c: (
                0 if c.get("asset_role", "satellite") == "core" else 1,
                c.get("dev_pct", 0),
            ))
            # First one stays actionable, rest downgraded
            for c in items[1:]:
                c["downgraded_from_action"] = c["strategy_action"]
                c["strategy_action"] = "observe"
                c["recommended_amount"] = 0.0
                c["downgrade_reason"] = f"同主题({theme})重复暴露，本周已选择{items[0]['fund_name']}"
                c["amount_source"] = "exposure_guard"

    # 2. Industry exposure guard
    for c in candidates:
        if c["strategy_action"] in ("fixed_dca", "dynamic_dca"):
            # Check if this fund's primary industries exceed thresholds
            # Simplified: check aggregate industry exposure
            max_ind = max(industry_exposure.values()) if industry_exposure else 0
            if max_ind > 0.40:
                c["exposure_status"] = "REVIEW_REQUIRED"
                c["exposure_reasons"] = f"行业暴露最大={max_ind*100:.0f}% > 40%"
            elif max_ind > 0.30 and c["strategy_action"] == "dynamic_dca":
                c["downgraded_from_action"] = c["strategy_action"]
                c["strategy_action"] = "observe"
                c["downgrade_reason"] = f"行业暴露={max_ind*100:.0f}% > 30%，停止动态加仓"

    # 3. Top10 overlap check
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if candidates[i]["strategy_action"] in ("fixed_dca", "dynamic_dca") and \
               candidates[j]["strategy_action"] in ("fixed_dca", "dynamic_dca"):
                a_stocks = get_fund_top_holdings(session, candidates[i]["fund_code"])
                b_stocks = get_fund_top_holdings(session, candidates[j]["fund_code"])
                overlap = calculate_overlap(a_stocks, b_stocks)
                if overlap > 0.5:
                    # Downgrade lower priority one
                    candidates[j]["downgraded_from_action"] = candidates[j]["strategy_action"]
                    candidates[j]["strategy_action"] = "observe"
                    candidates[j]["recommended_amount"] = 0.0
                    candidates[j]["downgrade_reason"] = f"与{candidates[i]['fund_name']}持仓重叠{overlap*100:.0f}%"

    # 4. Portfolio amount cap
    total_rec = sum(c.get("recommended_amount", 0) or 0 for c in candidates)
    cap = WEEKLY_BUDGET * PORTFOLIO_CAP_MULTIPLIER
    if total_rec > cap:
        for c in candidates:
            if c["strategy_action"] not in ("fixed_dca", "dynamic_dca"):
                c["exposure_status"] = "REVIEW_REQUIRED"
                c["exposure_reasons"] = f"组合建议总额{total_rec:.0f} > 预算上限{cap:.0f}"

    return candidates
