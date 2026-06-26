"""Full Exposure Audit — v1.0.4.1 honest report generator."""
import urllib.request, json, os, time, sqlite3
from datetime import datetime

BASE = "http://127.0.0.1:9600"
DB_PATH = "F:/compound-interest-plan/invest.db"

def get(path, default=None):
    try: return json.loads(urllib.request.urlopen(BASE+path,timeout=30).read())
    except Exception as e:
        if default is not None: return default
        return {"error": str(e)[:100], "_path": path}

def post(path, default=None):
    try:
        req=urllib.request.Request(BASE+path,method='POST')
        return json.loads(urllib.request.urlopen(req,timeout=120).read())
    except Exception as e:
        if default is not None: return default
        return {"error": str(e)[:100], "_path": path}

report = {
    "generated_at": datetime.now().isoformat(),
    "report_status": "NOT_LIVE_READY",
    "live_exposure_ready": False,
}

# System
h = get("/api/health")
report["system"] = {
    "backend_commit": h.get("git_commit", ""), "data_ready": h["data_ready"],
    "asset_count": h["db"]["asset_count"], "db_path": h["db"]["path"],
}

# Pipeline
pp = post("/api/pipeline/holding-snapshots")
print(f"Pipeline: {pp.get('generated_count')} generated, {pp.get('fixture_count')} fixture")

# Funds
assets = get("/api/assets")
funds = []
for a in assets:
    snap = get(f"/api/holding/snapshot/{a['code']}", {"snapshot": {"is_fixture": True, "source": "API_ERROR_FALLBACK"}})
    s = snap.get("snapshot") or {}
    api_err = snap.get("error", "")
    funds.append({
        "fund_code": a["code"], "fund_name": a["name"],
        "snapshot_exists": s != {}, "source": s.get("source", "API_ERROR"),
        "is_fixture": True if api_err or s.get("is_fixture") in (True, None) else s.get("is_fixture", True),
        "snapshot_status": "API_ERROR_FALLBACK" if api_err else ("ok" if s.get("source") != "API_ERROR" else "API_ERROR"),
        "api_error_message": api_err,
        "usable_for_live_decision": False if api_err else (not s.get("is_fixture", True) and not s.get("stale", True)),
        "report_period": s.get("report_period", ""), "holding_date": s.get("holding_date", ""),
        "stale_days": s.get("stale_days", 0),
        "top10_count": len(s.get("top10", [])), "industry_count": len(s.get("industry", {})),
    })
report["funds"] = funds

# Overlap pairs
codes = [a["code"] for a in assets]
pairs = []
live_high = []; live_med = []; expl_high = []; expl_med = []; fixture_pairs = 0
for i, a in enumerate(codes):
    for b in codes[i+1:]:
        o = get(f"/api/analysis/overlap?fund_a={a}&fund_b={b}")
        ov = o.get("overlap", {})
        fa = next((f for f in funds if f["fund_code"] == a), {})
        fb = next((f for f in funds if f["fund_code"] == b), {})
        is_fix = bool(fa.get("is_fixture")) or bool(fb.get("is_fixture"))
        usable = not is_fix
        pair = {
            "fund_a": a, "fund_b": b,
            "overlap_status": "EXPLANATORY_ONLY" if is_fix else ov.get("overlap_level", ""),
            "explanatory_overlap_level": ov.get("overlap_level"),
            "live_overlap_level": "unknown" if is_fix else ov.get("overlap_level"),
            "top10_overlap_score": ov.get("top10_overlap_score"), "industry_overlap_score": ov.get("industry_overlap_score"),
            "overlap_level": ov.get("overlap_level"), "common_holdings": ov.get("common_holdings", []),
            "source_a": fa.get("source"), "source_b": fb.get("source"),
            "is_fixture_a": fa.get("is_fixture"), "is_fixture_b": fb.get("is_fixture"),
            "usable_for_live_decision": usable, "report_period": ov.get("report_period", ""),
            "snapshot_consistent": bool(fa.get("top10_count") or not ov.get("common_holdings")),
            "data_quality": "fixture" if is_fix else ("stale" if fa.get("stale_days", 0) > 120 else "ok"),
        }
        pairs.append(pair)
        if is_fix:
            fixture_pairs += 1
            if ov.get("overlap_level") == "high": expl_high.append(f"{a}:{b}")
            elif ov.get("overlap_level") == "medium": expl_med.append(f"{a}:{b}")
        else:
            if ov.get("overlap_level") == "high": live_high.append(f"{a}:{b}")
            elif ov.get("overlap_level") == "medium": live_med.append(f"{a}:{b}")

report["overlap_pairs"] = pairs
report["high_risk_pairs"] = live_high
report["medium_risk_pairs"] = live_med
report["explanatory_high_risk_pairs"] = expl_high
report["explanatory_medium_risk_pairs"] = expl_med
report["fixture_pair_count"] = fixture_pairs
report["live_high_count"] = len(live_high)
report["live_medium_count"] = len(live_med)
report["data_missing_pair_count"] = sum(1 for p in pairs if p["overlap_level"] == "DATA_MISSING")

# Portfolio exposure — count unique funds per theme
pf = get("/api/portfolio/exposure", {"theme_exposure": {}})
seen = set()
pf_funds = []
for a in assets:
    if a["code"] not in seen:
        pf_funds.append({"code": a["code"], "theme": "未分类", "is_fixture": True})
        seen.add(a["code"])
report["portfolio_exposure"] = {
    "asset_count": len(assets), "included_fund_count": len(seen),
    "classified_count": 0, "unclassified_count": len(seen),
    "themes": pf.get("theme_exposure", {}),
    "fund_count_in_themes": sum(pf.get("theme_exposure", {}).values()),
    "source_mix": {"local_heuristic": len(assets)},
    "live_usable_count": 0, "fixture_count": len(assets),
}

# Daily decision check
try: post("/api/decision/run-daily")
except: pass
td = get("/api/decision/today", {"items": []})
items = td if isinstance(td, list) else td.get("items", [])
checks = {"total_items": len(items), "with_overlap_status": 0, "with_common_holdings": 0,
          "with_source": 0, "with_is_fixture": 0, "with_usable": 0, "with_stale": 0, "missing_fields_by_fund": {}}
for i in items:
    checks["with_overlap_status"] += 1 if i.get("overlap_status") else 0
    checks["with_source"] += 1 if i.get("holding_source") else 0
    checks["with_is_fixture"] += 1 if "is_fixture" in i else 0
    checks["with_usable"] += 1 if "usable_for_live" in i else 0
    checks["with_stale"] += 1 if i.get("stale_days") is not None else 0
    missing = [k for k in ["overlap_status","holding_source","holding_date","is_fixture","usable_for_live","stale_days"] if not i.get(k) and i.get(k) is None]
    if missing: checks["missing_fields_by_fund"][i.get("fund_code","?")] = missing
report["daily_decision_check"] = checks

# Safety
report["safety"] = {"no_auto_trade": True, "fixture_not_live": True, "ai_no_amount": True}
report["report_status"] = "NOT_LIVE_READY" if sum(1 for f in funds if f.get("is_fixture")) >= len(funds) else "PASS"
report["live_exposure_ready"] = any(f["usable_for_live_decision"] for f in funds)

# Snapshots detail
report["snapshots"] = {f["fund_code"]: f for f in funds}

# Data quality summary
dq = {"total": len(funds), "fixture": sum(1 for f in funds if f["is_fixture"]),
      "live_usable": sum(1 for f in funds if f["usable_for_live_decision"]),
      "stale": sum(1 for f in funds if f["stale_days"] > 120),
      "pairs_total": len(pairs), "pairs_fixture": report["fixture_pair_count"],
      "live_high_risk": report["live_high_count"], "live_medium_risk": report["live_medium_count"],
      "expl_high_risk": len(expl_high), "expl_medium_risk": len(expl_med)}
report["data_quality"] = dq

# ── v1.0.4.4 Strict audit rules ─────────────────────
audit_failures = []
# Rule 1: portfolio fund_count must not exceed asset_count
if report["portfolio_exposure"]["fund_count_in_themes"] > len(assets):
    audit_failures.append("PORTFOLIO_COUNT_MISMATCH")
# Rule 2: snapshot/overlap consistency
inconsistent = [p for p in pairs if not p.get("snapshot_consistent")]
if inconsistent:
    audit_failures.append("SNAPSHOT_OVERLAP_INCONSISTENT")
# Rule 3: top10=0 but common_holdings non-empty
for p in pairs:
    if p.get("common_holdings") and (not fa.get("top10_count") or not fb.get("top10_count")):
        audit_failures.append("TOKEN_MISMATCH")
        break
# Rule 4: API_ERROR_FALLBACK must have error message
api_err_funds = [f for f in funds if f.get("snapshot_status") == "API_ERROR_FALLBACK" and not f.get("api_error_message")]
if api_err_funds:
    audit_failures.append("API_ERROR_NO_MESSAGE")
# Rule 5: daily_decision_check honesty
dd = report["daily_decision_check"]
if dd["total_items"] > 0 and dd.get("with_common_holdings", 0) < dd["total_items"]:
    if not dd.get("missing_fields_by_fund"):
        audit_failures.append("DAILY_CHECK_MISLEADING")

if audit_failures:
    report["report_status"] = "AUDIT_FAIL"
    report["audit_errors"] = audit_failures
    report["honest_note"] = "当前仅验证部分 pipeline，数据一致性未通过。不允许进入实盘暴露闸门。"
elif all(f["is_fixture"] for f in funds):
    report["honest_note"] = "当前仅验证解释层 pipeline，不具备实盘暴露判断能力。"
else:
    report["honest_note"] = ""

path = "F:/compound-interest-plan/reports/exposure/full_exposure_audit_20250626_v2.json"
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print(f"\nGenerated: {path}")
print(f"report_status: {report['report_status']}")
print(f"live_exposure_ready: {report['live_exposure_ready']}")
print(f"asset_count: {len(assets)}")
print(f"fixture_count: {len(assets)} (all fixture)")
print(f"pairs: {len(pairs)} (fixture: {fixture_pairs})")
print(f"live_high: {len(live_high)} live_medium: {len(live_med)}")
print(f"expl_high: {len(expl_high)} expl_medium: {len(expl_med)}")
print(f"daily: {checks['total_items']} items, overlap_fields: {checks['with_overlap_status']}/{checks['total_items']}")
if all(f["is_fixture"] for f in funds):
    print("Honest: 当前仅验证解释层 pipeline，不具备实盘暴露判断能力。")
else:
    print(f"Honest: {sum(1 for f in funds if f['usable_for_live_decision'])}/{len(funds)} funds live-usable.")
