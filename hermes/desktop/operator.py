"""operator.py — Natural language action dispatcher for Hermes Desktop Operator.

All actions route through this module. 
Never auto-trades. Never auto-confirms. Never writes SQLite directly.
"""

import sys
import os
import json
import yaml
import webbrowser
from pathlib import Path
from datetime import date
from typing import Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from hermes.desktop.process_manager import (
    check_api_running, start_api,
    check_scheduler_running, start_scheduler,
    open_gui, open_reports_dir, open_alerts_dir,
    stop_managed_processes, status as pm_status,
)

INTENT_MAP_PATH = Path(__file__).parent / "intent_map.yaml"


# ── Intent loading ─────────────────────────────────

def load_intents() -> dict:
    with open(INTENT_MAP_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["intents"]


def match_intent(user_input: str) -> Optional[str]:
    """Match user NL input to an action name. Returns None if no match."""
    user_lower = user_input.lower().strip()
    intents = load_intents()

    for name, intent in intents.items():
        for example in intent.get("examples", []):
            if example.lower() in user_lower or user_lower in example.lower():
                return name
    return None


def list_intents() -> list:
    """Return list of (action, description, examples) for display."""
    intents = load_intents()
    return [
        {
            "action": name,
            "description": i.get("description", ""),
            "examples": i.get("examples", [])[:3],
        }
        for name, i in intents.items()
    ]


# ── Actions ────────────────────────────────────────

def action_open_system() -> Dict[str, Any]:
    """Complete system startup: API + Scheduler + GUI."""
    steps = []

    # API
    if not check_api_running():
        steps.append("Starting API...")
        start_api()
        import time; time.sleep(2)
        api_ok = check_api_running()
        steps.append(f"API: {'OK' if api_ok else 'FAIL (check logs/api.log)'}")
    else:
        steps.append("API: already running")

    # Scheduler
    if not check_scheduler_running():
        steps.append("Starting Scheduler...")
        start_scheduler()
        import time; time.sleep(1)
        sched_ok = check_scheduler_running()
        steps.append(f"Scheduler: {'OK' if sched_ok else 'FAIL (check logs/scheduler.log)'}")
    else:
        steps.append("Scheduler: already running")

    # GUI
    steps.append("Opening GUI...")
    gui_ok = open_gui()
    steps.append(f"GUI: {'OK (http://localhost:8501)' if gui_ok else 'FAIL (check logs/gui.log)'}")

    return {"action": "open_system", "steps": steps, "status": pm_status()}


def action_open_gui_only() -> Dict[str, Any]:
    if not check_api_running():
        start_api()
        import time; time.sleep(2)
    gui_ok = open_gui()
    return {
        "action": "open_gui",
        "gui_ok": gui_ok,
        "url": "http://localhost:8501",
        "status": pm_status(),
    }


def action_today_status() -> Dict[str, Any]:
    """Read latest snapshot/plan, return PASS/BLOCKED status."""
    try:
        from hermes.runtime.tool_executor import execute_tool
        from hermes.runtime.tool_registry import load_registry
        load_registry()

        snap = execute_tool("latest_snapshot", {"fund_code": "000083"})
        plan = execute_tool("latest_plan", {"fund_code": "000083"})

        if "error" in snap or "error" in plan:
            return {"action": "today_status", "status": "API_ERROR", "detail": snap.get("error") or plan.get("error")}

        action_ok = plan.get("action_allowed", False)
        rec = plan.get("recommended_amount")
        source = snap.get("proxy_source", snap.get("nav_source", "?"))
        trusted = str(source).lower() != "mock"
        proxy_date = snap.get("proxy_date", "")
        nav_date = snap.get("nav_date", "")
        today_str = date.today().isoformat()

        # signal_ready: proxy data is from today and trusted
        signal_ready = (
            trusted
            and source.lower() != "mock"
            and plan.get("risk_guard_passed", False)
            and proxy_date == today_str
        )
        # nav_ready: fund NAV is from today
        nav_ready = nav_date == today_str if nav_date else False

        result = {
            "action": "today_status",
            "fund_code": "000083",
            "proxy_code": snap.get("proxy_code", "000932"),
            "fund_nav": snap.get("nav"),
            "nav_date": nav_date,
            "nav_ready": nav_ready,
            "proxy_date": proxy_date,
            "signal_ready": signal_ready,
            "data_source": source,
            "trusted": trusted,
            "dev_pct": plan.get("dev_pct", 0),
            "level": plan.get("level"),
            "risk_guard": "PASS" if action_ok else "FAIL",
            "action_allowed": action_ok,
            "recommended_amount": rec if action_ok else None,
            "status": "PASS" if action_ok else "BLOCKED",
        }

        if action_ok and rec:
            result["message"] = (
                f"000083 | 代理指数 {result['proxy_code']} | 偏离: {result['dev_pct']*100:.2f}%"
                f" | 估值: {result['level']}\n"
                f"risk_guard: {result['risk_guard']} | action_allowed: true\n"
                f"recommended_amount: ¥{rec:.2f}（仅供人工复核）\n\n"
                f"说明：15:00 后生成的是基于今日代理指数收盘信号的复利计划结论；"
                f"实际基金交易确认日以平台规则为准。\n"
                f"基金当日 NAV 如未更新，仅影响持仓估值展示。\n"
                f"真实交易仍需在 GUI 中人工确认。"
            )
        else:
            result["message"] = "BLOCKED — 数据异常，需要人工复核。本次不输出买入金额。"
            result["block_reason"] = (
                f"source={source} (untrusted)" if not trusted
                else "risk_guard failed" if not action_ok
                else "proxy data not ready" if not signal_ready
                else "unknown"
            )

        return result
    except Exception as e:
        return {"action": "today_status", "status": "API_ERROR", "detail": str(e)}


def action_run_daily_sample() -> Dict[str, Any]:
    from hermes.runtime.run_once import run_daily_sample
    # Redirect stdout for clean output
    run_daily_sample()
    return {"action": "run_daily_sample", "status": "completed"}


def action_run_weekly_review() -> Dict[str, Any]:
    from hermes.runtime.run_once import run_weekly_review
    run_weekly_review()
    return {"action": "run_weekly_review", "status": "completed"}


def action_open_report(kind: str = "daily") -> Dict[str, Any]:
    d = open_reports_dir() / kind
    if not d.exists():
        return {"action": f"open_{kind}_report", "status": "no_reports", "path": str(d)}
    files = sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"action": f"open_{kind}_report", "status": "no_reports", "path": str(d)}
    path = files[0]
    try:
        webbrowser.open(str(path))
    except Exception:
        pass
    return {"action": f"open_{kind}_report", "path": str(path), "preview": path.read_text(encoding="utf-8")[:500]}


def action_open_alerts() -> Dict[str, Any]:
    d = open_alerts_dir()
    files = sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "action": "open_alerts",
        "path": str(d),
        "alert_count": len(files),
        "latest": str(files[0].name) if files else None,
    }


def action_backup_db() -> Dict[str, Any]:
    from hermes.runtime.tool_executor import execute_tool
    from hermes.runtime.tool_registry import load_registry
    load_registry()
    result = execute_tool("backup_db")
    if "error" in result:
        return {"action": "backup_db", "status": "FAILED", "error": result["error"]}
    return {"action": "backup_db", "status": "ok", "backup_path": result.get("backup_path")}


def action_stop_system() -> Dict[str, Any]:
    stopped = stop_managed_processes()
    return {"action": "stop_system", "stopped": stopped, "message": f"Stopped: {', '.join(stopped) if stopped else 'nothing to stop'}"}


# ── Dispatch ───────────────────────────────────────

ACTION_MAP = {
    "open_system": action_open_system,
    "open_gui": action_open_gui_only,
    "today_status": action_today_status,
    "run_daily_sample": action_run_daily_sample,
    "run_weekly_review": action_run_weekly_review,
    "open_daily_report": lambda: action_open_report("daily"),
    "open_weekly_report": lambda: action_open_report("weekly"),
    "open_alerts": action_open_alerts,
    "backup_db": action_backup_db,
    "stop_system": action_stop_system,
}


def dispatch(action_name: str) -> Dict[str, Any]:
    """Execute an action by name. Returns result dict."""
    if action_name not in ACTION_MAP:
        return {"error": f"Unknown action: {action_name}", "available": list(ACTION_MAP.keys())}
    return ACTION_MAP[action_name]()


def dispatch_nl(user_input: str) -> Dict[str, Any]:
    """Match NL input to action and execute. Returns result dict."""
    action = match_intent(user_input)
    if not action:
        return {
            "error": "No matching intent found",
            "input": user_input,
            "hint": "Available commands: " + ", ".join(ACTION_MAP.keys()),
        }
    return dispatch(action)
