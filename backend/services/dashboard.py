"""v1.7 Dashboard — aggregate system state for read-only display."""
import json
from datetime import datetime, date, timedelta
from sqlmodel import Session, select
from db.models import DailyDecision, UserDecision, Asset, FundHoldingSnapshot


def get_dashboard(session: Session) -> dict:
    """Return a complete read-only dashboard snapshot."""
    now = datetime.now()
    today_str = date.today().isoformat()

    # Assets
    assets = session.exec(select(Asset)).all()
    asset_list = [{"code": a.code, "name": a.name} for a in assets]

    # Today's decisions
    decisions = session.exec(select(DailyDecision).where(
        DailyDecision.date >= today_str
    ).order_by(DailyDecision.date.desc())).all()

    # Action counts
    actions = {"BUY": 0, "OBSERVE": 0, "WATCH": 0, "REVIEW_REQUIRED": 0, "BLOCKED": 0, "NO_ACTION": 0}
    user_acts = {"executed": 0, "skipped": 0, "observed": 0, "reviewed": 0, "acknowledged": 0, "pending": 0}

    for dd in decisions:
        sa = dd.strategy_action or ""
        if sa in ("fixed_dca", "dynamic_dca"): actions["BUY"] += 1
        elif sa == "take_profit_watch": actions["WATCH"] += 1
        elif sa == "observe": actions["OBSERVE"] += 1
        elif sa == "blocked": actions["BLOCKED"] += 1
        else: actions["NO_ACTION"] += 1

        ud = session.exec(select(UserDecision).where(
            UserDecision.daily_decision_id == dd.id
        )).first()
        ua = ud.user_action if ud else "pending"
        user_acts[ua] = user_acts.get(ua, 0) + 1

    # Snapshot coverage
    snapshots = session.exec(select(FundHoldingSnapshot)).all()
    src_counts = {}
    for s in snapshots:
        src_counts[s.source] = src_counts.get(s.source, 0) + 1

    # Valuation summary
    from services.valuation import PROXY_MAP
    val_summary = {"ready": 0, "weak_proxy": 0, "bond_pending": 0, "source_error": 0}
    for code, p in PROXY_MAP.items():
        st = p.get("status", "ok")
        if st == "weak_proxy": val_summary["weak_proxy"] += 1
        elif st == "bond_pending": val_summary["bond_pending"] += 1
        elif st == "ok": val_summary["source_error"] += 1

    # Top10-only exposure status
    exposure = {
        "status": "TOP10_ONLY_READY",
        "heavy_position_overlap_ready": len(snapshots) >= 2,
        "full_exposure_ready": False,
        "industry_data_missing": all(
            not json.loads(s.industry_distribution_json) for s in snapshots
        ) if snapshots else True,
    }

    return {
        "generated_at": now.isoformat(),
        "assets": {"count": len(assets), "list": asset_list},
        "today": {
            "decision_count": len(decisions),
            "actions": actions,
            "user_actions": user_acts,
            "pending": user_acts.get("pending", 0),
        },
        "snapshots": {"count": len(snapshots), "sources": src_counts},
        "valuation": val_summary,
        "exposure": exposure,
        "safety": {
            "no_auto_trade": True,
            "read_only": True,
        }
    }
