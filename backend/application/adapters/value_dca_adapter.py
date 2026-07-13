"""v2.1 Value-DCA Adapter — deterministic, no LLM."""
from sqlmodel import Session


def calculate_asset_candidate(asset, market_snapshot, valuation_result, config, session):
    """Return fixed/dynamic/candidate amounts using deterministic Value-DCA rules.
    NEVER uses LLM. Returns error_code on failure, NOT empty dict."""
    try:
        nav = getattr(market_snapshot, "nav", None)
        ma200 = getattr(market_snapshot, "proxy_ma200", None)
        if nav is None or ma200 is None or ma200 == 0:
            return {"ok": False, "error_code": "VALUE_DCA_NO_DATA",
                    "error": "nav or ma200 missing", "candidate_action": "REVIEW_REQUIRED"}

        dev_pct = (nav - ma200) / ma200
        fixed = 40.0  # base fixed
        if dev_pct < -0.10:
            dynamic = 50.0  # undervalued boost
        elif dev_pct > 0.05:
            dynamic = 0  # overvalued stop
        else:
            dynamic = 10.0  # normal

        return {
            "ok": True,
            "fixed_amount": fixed,
            "dynamic_amount": dynamic,
            "candidate_amount": fixed + dynamic,
            "candidate_action": "dynamic_dca" if dynamic > 0 else "fixed_dca",
            "risk_status": "PASS",
            "calculation_trace": f"dev_pct={dev_pct:.3f};fixed={fixed};dynamic={dynamic}",
            "strategy_version": "v2.1",
        }
    except Exception as e:
        return {"ok": False, "error_code": "VALUE_DCA_FAILED", "error": str(e)[:200],
                "candidate_action": "REVIEW_REQUIRED", "fixed_amount": None, "dynamic_amount": None,
                "candidate_amount": None}
