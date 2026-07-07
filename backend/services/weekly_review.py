"""v1.6 Weekly Review — aggregate weekly decision/action/valuation stats."""
import json
from datetime import datetime, date, timedelta
from sqlmodel import Session, select
from db.models import DailyDecision, UserDecision, FundHoldingSnapshot


def generate_weekly_review(session: Session, days: int = 7) -> dict:
    """Generate a weekly review report from recent decisions."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    decisions = session.exec(select(DailyDecision).where(
        DailyDecision.date >= cutoff
    ).order_by(DailyDecision.date.desc())).all()

    if not decisions:
        return {"ok": False, "reason": "no decisions in period", "days": days}

    # Aggregate stats
    actions = {"BUY": 0, "OBSERVE": 0, "WATCH": 0, "REVIEW_REQUIRED": 0, "BLOCKED": 0, "NO_ACTION": 0}
    user_actions = {"executed": 0, "skipped": 0, "observed": 0, "reviewed": 0, "acknowledged": 0, "pending": 0}
    unreviewed = []
    valuation = {"ready": 0, "source_error": 0, "weak_proxy": 0, "bond_pending": 0, "data_missing": 0}
    overlap_items = []

    for dd in decisions:
        # Parse strategy_action for action counting
        sa = dd.strategy_action or ""
        if sa in ("fixed_dca", "dynamic_dca"): actions["BUY"] += 1
        elif sa == "take_profit_watch": actions["WATCH"] += 1
        elif sa == "observe": actions["OBSERVE"] += 1
        elif sa == "blocked": actions["BLOCKED"] += 1
        else: actions["NO_ACTION"] += 1

        # User action
        ud = session.exec(select(UserDecision).where(
            UserDecision.daily_decision_id == dd.id
        )).first()
        ua = ud.user_action if ud else "pending"
        user_actions[ua] = user_actions.get(ua, 0) + 1

        if ua == "pending" and dd.override_exposure_guard:
            unreviewed.append({"fund_code": dd.fund_code, "date": dd.date, "decision_id": dd.id})

        # Check for overlap evidence
        if dd.downgrade_reason and ("重叠" in (dd.downgrade_reason or "") or "top10" in (dd.downgrade_reason or "").lower()):
            overlap_items.append({"fund_code": dd.fund_code, "reason": dd.downgrade_reason, "date": dd.date})

    # Valuation summary (from proxy map)
    from services.valuation import PROXY_MAP
    for code, proxy in PROXY_MAP.items():
        st = proxy.get("status", "ok")
        if st == "bond_pending": valuation["bond_pending"] += 1
        elif st == "weak_proxy": valuation["weak_proxy"] += 1
        else: valuation["source_error"] += 1  # sandbox: all akshare fail → source_error

    return {
        "period": f"past {days} days",
        "decision_count": len(decisions),
        "actions": actions,
        "user_actions": user_actions,
        "unreviewed_count": len(unreviewed),
        "unreviewed": unreviewed[:3],
        "overlap_items": overlap_items[:5],
        "valuation_summary": valuation,
        "valuation_note": "本周估值层无可用真实数据，仅记录proxy状态，不参与投资判断。" if valuation["ready"] == 0 else "",
        "no_auto_trade": True,
    }
