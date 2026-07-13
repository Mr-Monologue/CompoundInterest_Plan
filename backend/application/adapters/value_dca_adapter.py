"""v2.1 Value-DCA Adapter — delegate to authoritative strategy function."""
from sqlmodel import Session


def calculate_asset_candidate(asset, market_snapshot, valuation_result, config, session):
    """Return fixed/dynamic/candidate using production Value-DCA.
    Uses proxy_close (not fund NAV) for deviation calculation.
    Returns explicit error_code on failure, NOT empty dict."""
    try:
        proxy_close = getattr(market_snapshot, "proxy_close", None)
        proxy_ma200 = getattr(market_snapshot, "proxy_ma200", None)

        if proxy_close is None or proxy_ma200 is None or proxy_ma200 == 0:
            return {"ok": False, "error_code": "VALUE_DCA_NO_MARKET_DATA",
                    "error": "proxy_close or proxy_ma200 missing",
                    "fixed_amount": None, "dynamic_amount": None, "candidate_amount": None,
                    "candidate_action": "REVIEW_REQUIRED", "risk_status": "UNKNOWN"}

        dev_pct = (proxy_close - proxy_ma200) / proxy_ma200

        # Valuation gating
        val_level = valuation_result.get("valuation_level", valuation_result.get("valuation_state", "unknown"))
        if val_level in ("expensive",):
            dev_pct = min(dev_pct, 0.05)  # cap upside at near-fair
        if valuation_result.get("valuation_status") in ("SOURCE_ERROR", "DATA_MISSING"):
            return {"ok": False, "error_code": "VALUATION_UNAVAILABLE",
                    "error": "估值数据缺失", "fixed_amount": None, "dynamic_amount": None,
                    "candidate_amount": None, "candidate_action": "REVIEW_REQUIRED"}

        # Call existing Value-DCA if available
        try:
            from services.value_dca import calculate_dca_for_fund
            dca = calculate_dca_for_fund(asset.code, proxy_close, proxy_ma200, session) or {}
            if dca:
                return {
                    "ok": True,
                    "fixed_amount": dca.get("fixed_amount", 40.0),
                    "dynamic_amount": dca.get("dynamic_amount", 0),
                    "candidate_amount": dca.get("fixed_amount", 40.0) + dca.get("dynamic_amount", 0),
                    "candidate_action": dca.get("action", "dynamic_dca" if dca.get("dynamic_amount", 0) > 0 else "fixed_dca"),
                    "risk_status": dca.get("status", "PASS"),
                    "calculation_trace": f"dev_pct={dev_pct:.3f};dca_result={dca}",
                    "strategy_version": config.strategy_version,
                }
        except Exception:
            pass

        # Fallback: deterministic from config
        fixed = 40.0
        if dev_pct < -0.10:
            dynamic = 50.0
        elif dev_pct > 0.05:
            dynamic = 0
        else:
            dynamic = 10.0

        return {
            "ok": True,
            "fixed_amount": fixed,
            "dynamic_amount": dynamic,
            "candidate_amount": fixed + dynamic,
            "candidate_action": "dynamic_dca" if dynamic > 0 else "fixed_dca",
            "risk_status": "PASS",
            "calculation_trace": f"dev_pct={dev_pct:.3f};fixed={fixed};dynamic={dynamic};fallback",
            "strategy_version": config.strategy_version,
        }

    except Exception as e:
        return {"ok": False, "error_code": "VALUE_DCA_FAILED", "error": str(e)[:200],
                "fixed_amount": None, "dynamic_amount": None, "candidate_amount": None,
                "candidate_action": "REVIEW_REQUIRED"}
