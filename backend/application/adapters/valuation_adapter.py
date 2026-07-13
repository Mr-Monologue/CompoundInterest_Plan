"""v2.1 Valuation Adapter — bridges PROXY_MAP to pipeline."""
from services.valuation import PROXY_MAP


def get_valuation_state(asset_code):
    """Return valuation dict from proxy mapping. Never returns proxy_status as valuation_state."""
    proxy = PROXY_MAP.get(asset_code, {})
    proxy_status = proxy.get("status", "unknown")
    fit = proxy.get("fit_score", 0)

    if proxy_status == "bond_pending":
        return {"proxy_status": proxy_status, "valuation_status": "bond_pending",
                "valuation_state": "unknown", "valuation_score": None,
                "source": "PROXY_MAP", "evidence": {"proxy": proxy.get("name"), "note": "债券估值待开发"}}
    if proxy_status == "weak_proxy":
        return {"proxy_status": "WEAK_PROXY", "valuation_status": "WEAK_PROXY",
                "valuation_state": "REVIEW_REQUIRED", "valuation_score": None,
                "source": "PROXY_MAP", "evidence": {"proxy": proxy.get("name"), "fit": fit}}

    try:
        from services.valuation import fetch_valuation
        val = fetch_valuation(asset_code)
        vs = val.get("level", val.get("valuation_status", "unknown"))
        return {
            "proxy_status": proxy_status,
            "valuation_status": val.get("valuation_status", "ok"),
            "valuation_state": vs,
            "valuation_score": val.get("score"),
            "source": val.get("source", "PROXY_MAP"),
            "valuation_date": val.get("date", ""),
            "evidence": val.get("evidence", {}),
        }
    except Exception as e:
        return {"proxy_status": proxy_status, "valuation_status": "SOURCE_ERROR",
                "valuation_state": "unknown", "valuation_score": None,
                "source": "PROXY_MAP", "evidence": {"error": str(e)[:200]}}
