"""v1.0.1 Exposure API Router — AI exposure analysis endpoints."""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select
import json

from db.database import get_session
from db.models import Asset, FundHoldingSnapshot, FundExposureAnalysis, FundOverlap
from services.ai_exposure_analyst import analyze_fund_exposure
from services.exposure_calculator import compute_fund_pair_overlap
from services.holding_snapshot import generate_snapshot_from_local, run_pipeline_for_all

router = APIRouter(prefix="/api")

# ── Forbidden AI fields —────────────────────────────
FORBIDDEN_FIELDS = {"recommended_amount", "final_amount", "buy_amount", "action_allowed"}

def _sanitize_ai_result(result: dict) -> dict:
    """Remove any amount-related fields from AI output."""
    dropped = []
    for k in list(result.keys()):
        if k.lower() in FORBIDDEN_FIELDS or "amount" in k.lower() or "buy" in k.lower():
            dropped.append(k)
            del result[k]
    if dropped:
        result.setdefault("uncertainty", [])
        if isinstance(result.get("uncertainty"), list):
            result["uncertainty"].append(f"AI generated forbidden fields, dropped: {dropped}")
    return result


@router.post("/analysis/exposure/run/{fund_code}")
def run_exposure(fund_code: str, session: Session = Depends(get_session)):
    asset = session.exec(select(Asset).where(Asset.code == fund_code)).first()
    if not asset:
        return {"ok": False, "error": "Fund not found"}
    fund_data = {"fund_code": fund_code, "fund_name": asset.name, "top10": [], "industry_distribution": {}}
    snapshots = session.exec(select(FundHoldingSnapshot).where(FundHoldingSnapshot.fund_code == fund_code).order_by(FundHoldingSnapshot.updated_at.desc())).all()
    if snapshots:
        s = snapshots[0]
        try: fund_data["top10"] = json.loads(s.top10_json)
        except: pass
        try: fund_data["industry_distribution"] = json.loads(s.industry_distribution_json)
        except: pass

    result = analyze_fund_exposure(fund_data, "")
    result = _sanitize_ai_result(result)

    # Don't overwrite high-confidence AI with fallback
    existing = session.exec(select(FundExposureAnalysis).where(FundExposureAnalysis.fund_code == fund_code, FundExposureAnalysis.classification_source == "ai").order_by(FundExposureAnalysis.created_at.desc())).first()
    if existing and result.get("classification_source") == "local_rule" and existing.classification_confidence == "high":
        return {"ok": True, "fund_code": fund_code, "analysis": {"primary_theme": existing.primary_theme, "theme_bucket": existing.theme_bucket, "source": "ai", "confidence": "high", "cached": True}}

    f = FundExposureAnalysis(
        fund_code=fund_code, primary_theme=result.get("primary_theme", ""),
        theme_bucket=result.get("theme_bucket", ""),
        classification_source=result.get("classification_source", "local_rule"),
        classification_confidence=result.get("confidence", "low"),
        evidence_json=json.dumps(result.get("evidence", [])),
        uncertainty_json=json.dumps(result.get("uncertainty", [])),
        model_name=result.get("model_name", ""), model_version=result.get("model_version", ""),
        prompt_hash=result.get("prompt_hash", ""), input_hash=result.get("input_hash", ""),
    )
    session.add(f)
    session.commit()
    return {"ok": True, "fund_code": fund_code, "analysis": result}


@router.post("/analysis/exposure/run-all")
def run_all(session: Session = Depends(get_session)):
    assets = session.exec(select(Asset)).all()
    results = {}
    for a in assets:
        try:
            r = run_exposure(a.code, session)
            results[a.code] = (r.get("analysis") or {}).get("primary_theme", "error")
        except:
            results[a.code] = "error"
    return {"ok": True, "results": results}


@router.get("/analysis/exposure/{fund_code}")
def get_exposure(fund_code: str, session: Session = Depends(get_session)):
    analyses = session.exec(select(FundExposureAnalysis).where(FundExposureAnalysis.fund_code == fund_code).order_by(FundExposureAnalysis.created_at.desc())).all()
    if not analyses:
        return {"ok": True, "fund_code": fund_code, "analysis": None}
    a = analyses[0]
    return {"ok": True, "fund_code": fund_code, "analysis": {
        "primary_theme": a.primary_theme, "theme_bucket": a.theme_bucket,
        "source": a.classification_source, "confidence": a.classification_confidence,
        "evidence": json.loads(a.evidence_json) if a.evidence_json else [],
        "uncertainty": json.loads(a.uncertainty_json) if a.uncertainty_json else [],
        "model": a.model_name, "prompt_hash": a.prompt_hash, "input_hash": a.input_hash,
    }}


@router.get("/analysis/overlap")
def get_overlap(fund_a: str = "", fund_b: str = "", session: Session = Depends(get_session)):
    if not fund_a or not fund_b:
        return {"ok": False, "error": "fund_a and fund_b required"}
    sa = session.exec(select(FundHoldingSnapshot).where(FundHoldingSnapshot.fund_code == fund_a).order_by(FundHoldingSnapshot.updated_at.desc())).first()
    sb = session.exec(select(FundHoldingSnapshot).where(FundHoldingSnapshot.fund_code == fund_b).order_by(FundHoldingSnapshot.updated_at.desc())).first()
    fa = {"top10_json": sa.top10_json, "industry_distribution_json": sa.industry_distribution_json} if sa else {"top10_json": "[]", "industry_distribution_json": "{}"}
    fb = {"top10_json": sb.top10_json, "industry_distribution_json": sb.industry_distribution_json} if sb else {"top10_json": "[]", "industry_distribution_json": "{}"}
    result = compute_fund_pair_overlap(fa, fb)
    # Compute common holdings
    t10a = json.loads(sa.top10_json) if sa else []
    t10b = json.loads(sb.top10_json) if sb else []
    common = [s["name"] for s in t10a if s.get("name") in {h.get("name") for h in t10b}] if t10a and t10b else []
    result["common_holdings"] = common
    result["report_period"] = sa.report_period if sa else "unknown"
    result["overlap_status"] = result["overlap_level"] if result["overlap_level"] != "DATA_MISSING" else "DATA_MISSING"
    # Save to DB
    f = FundOverlap(fund_code_a=fund_a, fund_code_b=fund_b,
                    top10_overlap_score=result["top10_overlap_score"],
                    industry_overlap_score=result["industry_overlap_score"],
                    overlap_level=result["overlap_level"],
                    evidence_json=json.dumps(result.get("evidence", [])))
    session.add(f)
    session.commit()
    return {"ok": True, "fund_a": fund_a, "fund_b": fund_b, "overlap": result}


@router.get("/portfolio/exposure")
def get_portfolio_exposure(session: Session = Depends(get_session)):
    analyses = session.exec(select(FundExposureAnalysis).order_by(FundExposureAnalysis.created_at.desc())).all()
    themes = {}
    for a in analyses:
        tb = a.theme_bucket or "未分类"
        themes[tb] = themes.get(tb, 0) + 1
    return {"ok": True, "theme_exposure": themes}


@router.get("/holding/snapshot/{fund_code}")
def get_holding_snapshot(fund_code: str, session: Session = Depends(get_session)):
    snapshots = session.exec(select(FundHoldingSnapshot).where(FundHoldingSnapshot.fund_code == fund_code).order_by(FundHoldingSnapshot.updated_at.desc())).all()
    if not snapshots:
        return {"ok": True, "fund_code": fund_code, "snapshot": None, "status": "DATA_MISSING"}
    s = snapshots[0]
    stale_days = (datetime.now().date() - datetime.fromisoformat(s.holding_date[:10]).date()).days if s.holding_date else 999
    return {"ok": True, "fund_code": fund_code, "snapshot": {
        "report_period": s.report_period, "holding_date": s.holding_date,
        "source": s.source, "is_fixture": s.source == "local_heuristic",
        "top10": json.loads(s.top10_json) if s.top10_json else [],
        "industry": json.loads(s.industry_distribution_json) if s.industry_distribution_json else {},
        "stale_days": stale_days, "stale": stale_days > 120,
    }}


@router.post("/pipeline/holding-snapshots")
def run_holding_pipeline(session: Session = Depends(get_session)):
    result = run_pipeline_for_all(session)
    fixture = sum(1 for v in result.get("results", {}).values() if v == "local_heuristic")
    result["generated_count"] = len(result.get("results", {}))
    result["fixture_count"] = fixture
    result["missing_count"] = sum(1 for v in result.get("results", {}).values() if "error" in str(v))
    result["stale_count"] = 0
    return result