"""v1.0 Exposure Calculator — deterministic overlap scoring."""
import json, hashlib
from datetime import datetime

def top10_overlap(top10_a: list, top10_b: list) -> float:
    if not top10_a or not top10_b: return 0.0
    names_a = {s.get("name","").strip() for s in top10_a}
    names_b = {s.get("name","").strip() for s in top10_b}
    if not names_a or not names_b: return 0.0
    intersection = names_a & names_b
    union = names_a | names_b
    return len(intersection) / len(union) if union else 0.0

def industry_overlap(ind_a: dict, ind_b: dict) -> float:
    if not ind_a or not ind_b: return 0.0
    all_keys = set(ind_a.keys()) | set(ind_b.keys())
    if not all_keys: return 0.0
    a_norm = sum(v*v for v in ind_a.values()) ** 0.5
    b_norm = sum(v*v for v in ind_b.values()) ** 0.5
    if a_norm == 0 or b_norm == 0: return 0.0
    dot = sum(ind_a.get(k,0)*ind_b.get(k,0) for k in all_keys)
    return dot / (a_norm * b_norm)

def classify_overlap_level(top10_score: float, ind_score: float) -> str:
    if top10_score >= 0.5 or ind_score >= 0.7: return "high"
    if top10_score >= 0.3 or ind_score >= 0.4: return "medium"
    return "low"

def compute_fund_pair_overlap(fund_a: dict, fund_b: dict) -> dict:
    t10a_raw = fund_a.get("top10_json","[]")
    t10b_raw = fund_b.get("top10_json","[]")
    ind_a_raw = fund_a.get("industry_distribution_json","{}")
    ind_b_raw = fund_b.get("industry_distribution_json","{}")
    # Parse
    t10a = json.loads(t10a_raw) if isinstance(t10a_raw,str) else t10a_raw
    t10b = json.loads(t10b_raw) if isinstance(t10b_raw,str) else t10b_raw
    ind_a = json.loads(ind_a_raw) if isinstance(ind_a_raw,str) else ind_a_raw
    ind_b = json.loads(ind_b_raw) if isinstance(ind_b_raw,str) else ind_b_raw
    # Check for missing data
    if not t10a and not t10b:
        return {"top10_overlap_score": 0.0, "industry_overlap_score": 0.0, "overlap_level": "EXPLANATORY_ONLY",
                "overlap_reason": "SNAPSHOT_EMPTY", "evidence": ["Both funds have snapshot but no Top10 data"], "same_theme_downgrade": False}
    if not t10a or not t10b:
        return {"top10_overlap_score": 0.0, "industry_overlap_score": 0.0, "overlap_level": "EXPLANATORY_ONLY",
                "overlap_reason": "SNAPSHOT_EMPTY", "evidence": [f"One fund has no Top10 data" if t10a else "Fund A has no data" if not t10a else "Fund B has no data"], "same_theme_downgrade": False}
    t10 = top10_overlap(t10a, t10b)
    ind = industry_overlap(ind_a, ind_b)
    level = classify_overlap_level(t10, ind)
    coverage = "top10_only"
    return {"top10_overlap_score": round(t10,4), "industry_overlap_score": round(ind,4), "overlap_level": level,
            "overlap_scope": "heavy_position_only" if coverage == "top10_only" else "expanded",
            "coverage_level": coverage, "min_coverage_level": coverage,
            "top_holding_overlap_score": round(t10,4), "overlap_confidence": "medium" if coverage == "top10_only" else "high",
            "limitation": "仅基于前十大持仓，可能低估真实组合重叠" if coverage == "top10_only" else "",
            "evidence": [f"Top10 Jaccard: {t10:.2f}", f"Industry cosine: {ind:.2f}"], "same_theme_downgrade": t10>=0.5 or level=="high",
            "computed_at": datetime.now().isoformat()}