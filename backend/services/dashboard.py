"""v1.7 Dashboard — aggregate system state for read-only display."""
import json, os
from datetime import datetime, date, timedelta
from sqlmodel import Session, select
from db.models import DailyDecision, UserDecision, Asset, FundHoldingSnapshot


def get_dashboard(session: Session) -> dict:
    """Return a complete read-only dashboard snapshot. NEVER mutates state."""
    now = datetime.now()
    today_str = date.today().isoformat()

    assets = session.exec(select(Asset)).all()
    decisions = session.exec(select(DailyDecision).where(
        DailyDecision.date >= today_str).order_by(DailyDecision.date.desc())).all()

    actions = {"BUY": 0, "OBSERVE": 0, "WATCH": 0, "REVIEW_REQUIRED": 0, "BLOCKED": 0, "NO_ACTION": 0}
    user_acts = {"executed": 0, "skipped": 0, "observed": 0, "reviewed": 0, "acknowledged": 0, "pending": 0}

    for dd in decisions:
        sa = dd.strategy_action or ""
        if sa in ("fixed_dca", "dynamic_dca"): actions["BUY"] += 1
        elif sa == "take_profit_watch": actions["WATCH"] += 1
        elif sa == "observe": actions["OBSERVE"] += 1
        elif sa == "blocked": actions["BLOCKED"] += 1
        else: actions["NO_ACTION"] += 1
        ud = session.exec(select(UserDecision).where(UserDecision.daily_decision_id == dd.id)).first()
        user_acts[ud.user_action if ud else "pending"] = user_acts.get(ud.user_action if ud else "pending", 0) + 1

    snapshots = session.exec(select(FundHoldingSnapshot)).all()

    from services.valuation import PROXY_MAP
    val_summary = {"ready": 0, "weak_proxy": 0, "bond_pending": 0, "source_error": 0}
    for code, p in PROXY_MAP.items():
        st = p.get("status", "ok")
        if st == "weak_proxy": val_summary["weak_proxy"] += 1
        elif st == "bond_pending": val_summary["bond_pending"] += 1
        else: val_summary["source_error"] += 1

    exposure = {"status": "TOP10_ONLY_READY", "heavy_position_overlap_ready": len(snapshots) >= 2,
                "full_exposure_ready": False, "industry_data_missing": not any(
            json.loads(s.industry_distribution_json) for s in snapshots) if snapshots else True}

    return {
        "generated_at": now.isoformat(),
        "assets_count": len(assets),
        "today_decisions_summary": {"count": len(decisions), "actions": actions},
        "user_actions_summary": dict(user_acts),
        "pending_count": user_acts.get("pending", 0),
        "valuation_summary": val_summary,
        "exposure_summary": exposure,
        "weekly_review_summary": {"decision_count": len(decisions), "days": 7},
        "runtime_status": {"backend": "READY" if decisions is not None else "DEGRADED",
                           "snapshots": len(snapshots)},
        "safety": {"read_only": True, "no_auto_trade": True,
                   "no_amount_mutation": True, "no_pool_deduction": True}
    }
