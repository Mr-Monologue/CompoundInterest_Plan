"""v1.5.1 Valuation Layer — refined proxy index mapping."""
import os, json, time
from datetime import datetime, date
from sqlmodel import Session, select

# Refined proxy: fund → {index_code, name, reason, confidence, fit_score, status, is_bond}
# confidence: high/medium/weak | fit_score: 0-100 | status: ok/weak_proxy/bond_pending
PROXY_MAP = {
    "000083": {"index_code": "000932", "name": "中证消费", "reason": "消费行业混合，前10重仓食品饮料占比35%，中证消费指数最匹配",
               "confidence": "medium", "fit_score": 70, "status": "ok"},
    "001532": {"index_code": "000300", "name": "沪深300", "reason": "文体健康混合，持仓分散(消费/科技/金融/新能源)，无单一行业指数匹配",
               "confidence": "weak", "fit_score": 40, "status": "weak_proxy"},
    "002340": {"index_code": "000950", "name": "中证金融", "reason": "金融地产混合，前10重仓金融+地产占比43%，中证金融地产指数匹配",
               "confidence": "medium", "fit_score": 65, "status": "ok"},
    "000032": {"index_code": "CBA00101", "name": "中债-综合财富", "reason": "纯债基金，不使用PE/PB估值",
               "confidence": "N/A", "fit_score": 0, "status": "bond_pending", "is_bond": True},
    "003096": {"index_code": "000991", "name": "中证医药", "reason": "医药生物主题，前10 100%医药+生物科技，中证医药卫生指数替代创业板指",
               "confidence": "medium", "fit_score": 75, "status": "ok"},
    "005827": {"index_code": "000300", "name": "沪深300", "reason": "消费/金融/科技混合，持仓分散于三大行业，宽基指数兜底",
               "confidence": "weak", "fit_score": 45, "status": "weak_proxy"},
    "000071": {"index_code": "HSTECH", "name": "恒生科技", "reason": "港股QDII，恒生科技指数",
               "confidence": "medium", "fit_score": 60, "status": "ok"},
    "160422": {"index_code": "HSTECH", "name": "恒生科技", "reason": "港股QDII，恒生科技指数",
               "confidence": "medium", "fit_score": 60, "status": "ok"},
}




# Cache: only try akshare import once
_ak_available = None
def _try_akshare():
    global _ak_available
    if _ak_available is None:
        try:
            import akshare as ak
            _ak_available = ak
        except:
            _ak_available = False
    return _ak_available

def fetch_valuation(fund_code: str) -> dict:
    """Fetch valuation data for a fund via its proxy index."""
    proxy = PROXY_MAP.get(fund_code)
    if not proxy:
        return {"valuation_status": "DATA_MISSING", "proxy_status": "no_proxy", "stale_days": 999}

    result = {
        "proxy_index_code": proxy["index_code"],
        "proxy_index_name": proxy["name"],
        "proxy_reason": proxy["reason"],
        "proxy_confidence": proxy["confidence"],
        "proxy_fit_score": proxy["fit_score"],
        "proxy_status": proxy["status"],
    }

    # Bond funds — no PE/PB valuation
    if proxy.get("is_bond"):
        return {**result, "valuation_status": "bond_pending", "valuation_level": "unknown",
                "valuation_score": None, "source": "bond_proxy", "stale_days": 0,
                "evidence": "债券基金不使用PE/PB估值，预留久期/信用/利率指标"}

    if proxy["status"] == "weak_proxy":
        result["valuation_status"] = "WEAK_PROXY"
        result["valuation_level"] = "unknown"
        result["valuation_score"] = None
        result["evidence"] = f"代理指数({proxy['name']})匹配度低({proxy['fit_score']}/100)，估值仅参考"
        result["stale_days"] = 0
        return result

    try:
        ak = _try_akshare()
        if not ak: return {**result, "valuation_status": "SOURCE_ERROR", "error": "akshare_unavailable"}
        df = ak.index_value_name_funddb()
        if df is not None and len(df) > 0:
            index_code = proxy["index_code"]
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

                return {**result,
                    "valuation_status": "READY", "valuation_level": level,
                    "valuation_score": max(0, min(100, score)),
                    "pe_ttm": pe, "pe_percentile": pe_pct,
                    "pb": pb, "pb_percentile": pb_pct,
                    "dividend_yield": div, "dividend_yield_percentile": div_pct,
                    "source": "akshare/index_value", "valuation_date": str(date.today()),
                    "stale_days": 0,
                    "evidence": f"PE={pe:.1f}(P{pct_to_label(pe_pct)}), PB={pb:.1f}(P{pct_to_label(pb_pct)})",
                }
    except Exception as e:
        return {**result, "valuation_status": "SOURCE_ERROR", "error": str(e)[:100], "stale_days": 999}

    return {**result, "valuation_status": "DATA_MISSING", "stale_days": 999}


def pct_to_label(pct: float) -> str:
    if pct <= 20: return f"{pct:.0f}≈低估"
    if pct <= 40: return f"{pct:.0f}≈偏低"
    if pct <= 60: return f"{pct:.0f}≈合理"
    if pct <= 80: return f"{pct:.0f}≈偏高"
    return f"{pct:.0f}≈高估"
