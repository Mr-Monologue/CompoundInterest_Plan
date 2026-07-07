"""v1.8 Dashboard Todos — read-only aggregation of pending items and data issues."""
import json
from datetime import datetime, date, timedelta
from sqlmodel import Session, select
from db.models import DailyDecision, UserDecision, Asset, FundHoldingSnapshot


def get_dashboard_todos(session: Session) -> dict:
    """Return categorized pending items and data exceptions. NEVER mutates state."""
    now = datetime.now()
    today_str = date.today().isoformat()

    decisions = session.exec(select(DailyDecision).where(
        DailyDecision.date >= today_str).order_by(DailyDecision.date.desc())).all()
    snapshots = session.exec(select(FundHoldingSnapshot)).all()

    from services.valuation import PROXY_MAP

    # Section buckets
    must_handle = []
    review_required = []
    blocked = []
    data_issues = []
    pending_user_actions = []
    watch_items = []
    info_only = []

    for dd in decisions:
        ud = session.exec(select(UserDecision).where(UserDecision.daily_decision_id == dd.id)).first()
        ua = ud.user_action if ud else "pending"
        sa = dd.strategy_action or ""
        is_pending = ua == "pending"

        base = {"id": dd.id, "fund_code": dd.fund_code, "date": dd.date,
                "strategy_action": sa, "user_action": ua, "reason": dd.downgrade_reason or ""}

        # must_handle: BUY pending, REVIEW_REQUIRED not reviewed, BLOCKED not acknowledged
        if sa in ("fixed_dca", "dynamic_dca") and is_pending:
            must_handle.append({**base, "severity": "warning", "priority": "P1",
                               "action_hint": "人工复核后标记已完成或跳过"})
        elif (dd.override_exposure_guard or (dd.downgrade_reason or "").startswith("Top10")) and is_pending:
            review_required.append({**base, "severity": "warning", "priority": "P1",
                                    "action_hint": "开始复核", "requires_reason": True})
        elif sa == "blocked":
            blocked.append({**base, "severity": "critical", "priority": "P0", "action_hint": "查看阻断原因"})
        elif is_pending and sa in ("observe", "take_profit_watch"):
            watch_items.append({**base, "severity": "info", "priority": "P2", "action_hint": "加入观察记录"})

        # pending user actions (any pending)
        if is_pending:
            pending_user_actions.append({**base, "severity": "info", "priority": "P3",
                                          "action_hint": "查看今日计划并处理"})

    # Data issues
    if not snapshots:
        data_issues.append({"type": "no_snapshots", "severity": "warning", "priority": "P1",
                            "reason": "无持仓快照", "action_hint": "运行pipeline"})

    for code, p in PROXY_MAP.items():
        st = p.get("status", "ok")
        if st == "weak_proxy":
            data_issues.append({"type": "weak_proxy", "fund_code": code, "severity": "info",
                               "priority": "P2", "reason": f"估值代理较弱({p['name']}, fit={p['fit_score']})",
                               "action_hint": "估值仅供参考"})
        elif st == "bond_pending":
            info_only.append({"type": "bond_pending", "fund_code": code, "severity": "info",
                              "priority": "P3", "reason": "债券基金PE/PB估值待开发", "action_hint": "信息提示"})

    # System info
    info_only.append({"type": "top10_only", "severity": "info", "priority": "P3",
                      "reason": "持仓分析仅基于前十大重仓股，不是完整持仓穿透", "action_hint": "信息提示"})
    info_only.append({"type": "valuation_ready_0", "severity": "info", "priority": "P3",
                      "reason": "估值层无可用真实数据(本周)", "action_hint": "信息提示"})
    info_only.append({"type": "industry_missing", "severity": "info", "priority": "P3",
                      "reason": "行业数据缺失，未参与行业重叠判断", "action_hint": "信息提示"})

    summary = {
        "total": len(must_handle) + len(review_required) + len(blocked) + len(data_issues),
        "must_handle": len(must_handle), "review_required": len(review_required),
        "blocked": len(blocked), "data_issues": len(data_issues),
        "pending_user_actions": len(pending_user_actions), "watch_items": len(watch_items),
    }

    return {
        "ok": True, "read_only": True, "generated_at": now.isoformat(),
        "todo_summary": summary,
        "sections": {
            "must_handle": must_handle, "review_required": review_required,
            "blocked": blocked, "data_issues": data_issues,
            "pending_user_actions": pending_user_actions, "watch_items": watch_items,
            "info_only": info_only,
        },
        "safety": {"read_only": True, "no_auto_trade": True,
                   "no_amount_mutation": True, "no_pool_deduction": True},
    }
