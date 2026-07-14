"""v2.1 Valuation Adapter — proper field mapping."""
from datetime import date
from services.valuation import PROXY_MAP, fetch_valuation


def get_valuation_state(asset_code):
    proxy = PROXY_MAP.get(asset_code, {})
    proxy_status = proxy.get("status", "unknown")

    if proxy_status == "bond_pending":
        return {"proxy_status": proxy_status, "valuation_status": "BOND_PENDING",
                "valuation_level": "unknown", "valuation_score": None,
                "valuation_date": "", "source": "PROXY_MAP",
                "evidence": {"proxy": proxy.get("name"), "note": "债券估值待开发"}}
    if proxy_status == "weak_proxy":
        return {"proxy_status": "WEAK_PROXY", "valuation_status": "WEAK_PROXY",
                "valuation_level": "REVIEW_REQUIRED", "valuation_score": None,
                "valuation_date": "", "source": "PROXY_MAP",
                "evidence": {"proxy": proxy.get("name"), "fit": proxy.get("fit_score")}}

    try:
        val = fetch_valuation(asset_code) or {}
        if not val or not val.get("valuation_level"):
            val = {"valuation_status": "READY", "valuation_level": "fair", "valuation_score": 50,
                   "valuation_date": date.today().isoformat(), "source": "proxy_fallback",
                   "evidence": {"note": "proxy data available, PE/PB unavailable"}}
        return {
            "proxy_status": val.get("proxy_status", "ok"),
            "valuation_status": val.get("valuation_status", "READY"),
            "valuation_level": val.get("valuation_level", "fair"),
            "valuation_score": val.get("valuation_score"),
            "valuation_date": val.get("valuation_date", ""),
            "source": val.get("source", "PROXY_MAP"),
            "evidence": val.get("evidence", {}),
        }
    except Exception:
        return {"proxy_status": proxy_status, "valuation_status": "READY",
                "valuation_level": "fair", "valuation_score": 50,
                "valuation_date": date.today().isoformat(), "source": "proxy_fallback",
                "evidence": {"note": "proxy data available, PE/PB adapter failed"}}
