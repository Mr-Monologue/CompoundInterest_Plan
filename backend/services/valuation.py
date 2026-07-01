"""v1.5 Valuation Layer — proxy index valuation data."""
import os, json, time
from datetime import datetime, date
from sqlmodel import Session, select

# Proxy index mapping: fund_code → (index_code, index_name, reason)
PROXY_MAP = {
    "000083": ("000300", "沪深300", "消费行业混合，沪深300偏消费"),
    "001532": ("000300", "沪深300", "文体健康混合，沪深300"),
    "002340": ("000300", "沪深300", "金融地产混合，沪深300"),
    "000032": ("000012", "国债指数", "纯债基金，国债指数"),
    "003096": ("399006", "创业板指", "医药生物，创业板偏成长"),
    "005827": ("000300", "沪深300", "消费金融科技混合，沪深300"),
    "000071": ("HSTECH", "恒生科技", "港股QDII"),
    "160422": ("HSTECH", "恒生科技", "港股QDII"),
}

def fetch_valuation(fund_code: str) -> dict:
    """Fetch valuation data for a fund via its proxy index.
    Returns DATA_MISSING if unavailable."""
    proxy = PROXY_MAP.get(fund_code)
    if not proxy:
        return {"valuation_status": "DATA_MISSING", "source": "no_proxy", "stale_days": 999}

    index_code, name, reason = proxy
    try:
        import akshare as ak
        # Try index valuation
        df = ak.index_value_name_funddb()
        if df is not None and len(df) > 0:
            match = df[df["指数代码"].str.contains(index_code[:6], na=False)]
            if len(match) > 0:
                row = match.iloc[0]
                pe = float(row.get("市盈率", row.get("PE", 0)) or 0)
                pb = float(row.get("市净率", row.get("PB", 0)) or 0)
                div = float(row.get("股息率", 0) or 0)
                pe_pct = float(row.get("PE分位", 50) or 50)
                pb_pct = float(row.get("PB分位", 50) or 50)
                div_pct = float(row.get("股息率分位", 50) or 50)

                score = round((50-pe_pct)*0.4 + (50-pb_pct)*0.3 + (div_pct-50)*0.3 + 50)
                level = "undervalued" if score >= 65 else ("expensive" if score <= 35 else "fair")

                return {
                    "valuation_status": "READY",
                    "valuation_level": level,
                    "valuation_score": max(0, min(100, score)),
                    "pe_ttm": pe, "pe_percentile": pe_pct,
                    "pb": pb, "pb_percentile": pb_pct,
                    "dividend_yield": div, "dividend_yield_percentile": div_pct,
                    "proxy_index_code": index_code,
                    "proxy_index_name": name,
                    "proxy_reason": reason,
                    "source": "akshare/index_value",
                    "valuation_date": str(date.today()),
                    "stale_days": 0,
                    "evidence": f"PE={pe:.1f}(P{pct_to_label(pe_pct)}), PB={pb:.1f}(P{pct_to_label(pb_pct)})",
                }
    except Exception as e:
        return {"valuation_status": "SOURCE_ERROR", "error": str(e)[:100], "stale_days": 999}

    return {"valuation_status": "DATA_MISSING", "stale_days": 999}


def pct_to_label(pct: float) -> str:
    if pct <= 20: return f"{pct:.0f}≈低估"
    if pct <= 40: return f"{pct:.0f}≈偏低"
    if pct <= 60: return f"{pct:.0f}≈合理"
    if pct <= 80: return f"{pct:.0f}≈偏高"
    return f"{pct:.0f}≈高估"
