#!/usr/bin/env python3
"""run_once.py — Hermes Runtime 单次执行入口

Usage:
    python -m hermes.runtime.run_once daily_sample
    python -m hermes.runtime.run_once anomaly_watch
    python -m hermes.runtime.run_once weekly_review
"""

import sys
import os
from pathlib import Path
from datetime import date, datetime

# Ensure project root in path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from hermes.runtime.config import REPORT_DIR, ALERT_DIR
from hermes.runtime.tool_registry import load_registry, get_tool, tool_allowed
from hermes.runtime.tool_executor import execute_tool
from hermes.runtime.policy_checker import check_policy
from hermes.runtime.report_writer import (
    write_daily_report,
    write_blocked_alert,
    write_anomaly_alert,
    write_weekly_report,
)

# ── Daily Sample ────────────────────────────────────

def run_daily_sample():
    print("=== Hermes Runtime: daily_sample ===")
    load_registry()

    result = execute_tool("daily_sample", {"created_by": "hermes"})
    if "error" in result:
        print(f"❌ API error: {result['error']}")
        return

    # Handle batch response
    results = result.get("results", [result])
    for item in results:
        code = item.get("fund_code", "?")
        policy = check_policy(item)

        if policy["safe_to_display_amount"]:
            print(f"[{code}] ✅ PASS — recommended_amount: ¥{policy['recommended_amount']:.2f}")
            print(f"    （仅供人工复核）")
        else:
            print(f"[{code}] ⛔ BLOCKED — reasons: {'; '.join(policy['errors'])}")

        # Write reports
        path = write_daily_report(REPORT_DIR, item, policy)
        print(f"    📄 {path}")

        if not policy["safe_to_display_amount"]:
            path = write_blocked_alert(ALERT_DIR, item, policy)
            print(f"    🚨 {path}")

# ── Anomaly Watch ───────────────────────────────────

def run_anomaly_watch():
    print("=== Hermes Runtime: anomaly_watch ===")
    load_registry()

    anomalies = []

    # Get latest plan data
    plan = execute_tool("latest_plan", {"fund_code": "000083"})
    snap = execute_tool("latest_snapshot", {"fund_code": "000083"})

    # Check anomalies
    source = str(snap.get("proxy_source", snap.get("nav_source", ""))).lower()
    trusted = source != "mock"

    if not trusted:
        anomalies.append(f"source={source} (untrusted)")
    if plan.get("action_allowed") is False:
        anomalies.append("action_allowed=false")
    if not plan.get("action_allowed", True) and plan.get("recommended_amount") is not None:
        anomalies.append("P0 ANOMALY: BLOCKED but recommended_amount is not null")

    nav = snap.get("nav", 0)
    if nav is not None and (nav <= 0 or nav > 20):
        anomalies.append(f"NAV anomaly: {nav}")

    dev = plan.get("dev_pct", 0)
    if dev is not None and abs(dev) > 0.5:
        anomalies.append(f"dev_pct anomaly: {dev*100:.2f}%")

    data_date = snap.get("nav_date", "")
    if data_date:
        try:
            dd = datetime.strptime(data_date, "%Y-%m-%d").date()
            if (date.today() - dd).days > 3:
                anomalies.append(f"Data stale: {data_date} ({(date.today()-dd).days} days old)")
        except ValueError:
            pass

    if anomalies:
        path = write_anomaly_alert(ALERT_DIR, anomalies)
        print(f"⚠️  {len(anomalies)} anomalies → {path}")
        for a in anomalies:
            print(f"    - {a}")
    else:
        print("✅ No anomalies detected")

# ── Weekly Review ───────────────────────────────────

def run_weekly_review():
    print("=== Hermes Runtime: weekly_review ===")
    load_registry()

    result = execute_tool("weekly_review", {"days": 7})
    if "error" in result:
        print(f"❌ API error: {result['error']}")
        return

    path = write_weekly_report(REPORT_DIR, result)
    print(f"📄 {path}")
    print(f"    Total amount: ¥{result.get('total_amount', 0):.2f}")
    print(f"    Record count: {result.get('record_count', 0)}")
    print("    ⚠️ 不承诺收益，不预测涨跌。")


# ── CLI ─────────────────────────────────────────────

COMMANDS = {
    "daily_sample": run_daily_sample,
    "anomaly_watch": run_anomaly_watch,
    "weekly_review": run_weekly_review,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Usage: python -m hermes.runtime.run_once <command>")
        print(f"Commands: {list(COMMANDS.keys())}")
        sys.exit(1)

    COMMANDS[sys.argv[1]]()
