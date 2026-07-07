"""v1.9 Data Quality Workbench — scan, track, fix data issues."""
import json
from datetime import datetime
from sqlmodel import Session, select
from db.models import DataQualityIssue, FundHoldingSnapshot, Asset


def scan_issues(session: Session) -> dict:
    """Scan current system for data quality issues. Only mutates DataQualityIssue."""
    now = datetime.now()
    new_issues = []

    # Check snapshots
    snapshots = session.exec(select(FundHoldingSnapshot)).all()
    snapshot_codes = {s.fund_code for s in snapshots}
    assets = session.exec(select(Asset)).all()

    for a in assets:
        if a.code not in snapshot_codes:
            new_issues.append(upsert(session, a.code, "NO_SNAPSHOT", "holding_snapshot", "warning", "P1",
                                     {"reason": "Missing holding snapshot"}, "运行 pipeline 生成快照"))

    for s in snapshots:
        if s.source == "local_heuristic":
            new_issues.append(upsert(session, s.fund_code, "SOURCE_ERROR", "holding_snapshot", "warning", "P2",
                                     {"source": "local_heuristic"}, "接入 AKShare 真实数据"))
        if not json.loads(s.top10_json):
            new_issues.append(upsert(session, s.fund_code, "SNAPSHOT_EMPTY", "holding_snapshot", "warning", "P2",
                                     {"top10_empty": True}, "重试 pipeline"))

    # Valuation issues
    from services.valuation import PROXY_MAP
    for code, p in PROXY_MAP.items():
        st = p.get("status", "ok")
        if st == "weak_proxy":
            new_issues.append(upsert(session, code, "WEAK_PROXY", "proxy_mapping", "info", "P2",
                                     {"proxy": p["name"], "fit": p["fit_score"]},
                                     "重新评估 proxy 匹配度，考虑更合适的指数"))
        elif st == "bond_pending":
            new_issues.append(upsert(session, code, "VALUATION_DATA_MISSING", "valuation", "info", "P3",
                                     {"reason": "债券基估值待开发"}, "预留久期/信用评级指标"))

    # Check for industry data
    for s in snapshots:
        if not json.loads(s.industry_distribution_json):
            new_issues.append(upsert(session, s.fund_code, "INDUSTRY_DATA_MISSING", "exposure", "info", "P2",
                                     {"source": s.source}, "接入行业分类数据"))

    # Stale data check
    for s in snapshots:
        if s.holding_date:
            try:
                hd = datetime.fromisoformat(s.holding_date[:10])
                stale = (now - hd).days
                if stale > 120:
                    new_issues.append(upsert(session, s.fund_code, "STALE_DATA", "holding_snapshot", "warning", "P1",
                                             {"stale_days": stale}, "重新拉取最新持仓数据"))
            except: pass

    session.commit()
    return {"ok": True, "scanned": len(assets), "issues_created": len(set(i.id for i in new_issues if i))}


def upsert(session, fund_code, issue_type, module, severity, priority, evidence, fix):
    existing = session.exec(select(DataQualityIssue).where(
        DataQualityIssue.issue_type == issue_type,
        DataQualityIssue.related_fund_code == fund_code
    )).first()
    if existing:
        existing.last_seen_at = datetime.now()
        existing.severity = severity
        return existing
    iss = DataQualityIssue(issue_type=issue_type, related_fund_code=fund_code, related_module=module,
                           severity=severity, priority=priority, source="scan",
                           evidence_json=json.dumps(evidence, ensure_ascii=False),
                           suggested_fix=fix, status="OPEN")
    session.add(iss)
    return iss


def get_summary(session: Session) -> dict:
    issues = session.exec(select(DataQualityIssue)).all()
    open_issues = [i for i in issues if i.status == "OPEN"]
    return {
        "total_open": len(open_issues),
        "critical": sum(1 for i in open_issues if i.severity == "critical"),
        "warning": sum(1 for i in open_issues if i.severity == "warning"),
        "info": sum(1 for i in open_issues if i.severity == "info"),
        "by_type": {t: sum(1 for i in open_issues if i.issue_type == t) for t in set(i.issue_type for i in open_issues)},
        "by_module": {m: sum(1 for i in open_issues if i.related_module == m) for m in set(i.related_module for i in open_issues)},
        "fixable_count": sum(1 for i in open_issues if i.issue_type in ("NO_SNAPSHOT", "STALE_DATA")),
        "needs_human_count": sum(1 for i in open_issues if i.issue_type in ("WEAK_PROXY", "VALUATION_DATA_MISSING")),
        "safety": {"read_only": True, "no_auto_trade": True, "no_amount_mutation": True, "no_pool_deduction": True},
    }


def try_fix(session: Session, issue_id: int) -> dict:
    iss = session.get(DataQualityIssue, issue_id)
    if not iss:
        return {"ok": False, "error": "Not found"}
    iss.fix_attempt_count += 1
    audit = []

    if iss.issue_type == "NO_SNAPSHOT":
        from services.holding_snapshot import generate_snapshot
        result = generate_snapshot(iss.related_fund_code, "", session)
        iss.last_fix_result = "ok" if result.get("snapshot_status") != "SNAPSHOT_EMPTY" else "SOURCE_ERROR"
        iss.status = "FIXED" if iss.last_fix_result == "ok" else "OPEN"
        audit.append({"action": "generate_snapshot", "result": iss.last_fix_result})
    elif iss.issue_type == "STALE_DATA":
        from services.holding_snapshot import generate_snapshot
        generate_snapshot(iss.related_fund_code, "", session)
        iss.last_fix_result = "retried"
        iss.status = "CHECKING"
        audit.append({"action": "refresh_snapshot", "result": "retried"})
    else:
        iss.last_fix_result = "not_auto_fixable"
        iss.status = "NEEDS_HUMAN"
        audit.append({"action": "auto_fix_blocked", "reason": f"{iss.issue_type} requires human review"})

    iss.audit_log_json = json.dumps(json.loads(iss.audit_log_json) + audit, ensure_ascii=False)
    session.commit()
    return {"ok": True, "issue_id": issue_id, "fix_result": iss.last_fix_result, "status": iss.status}
