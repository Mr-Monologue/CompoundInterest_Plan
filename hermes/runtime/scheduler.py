#!/usr/bin/env python3
"""scheduler.py — Hermes Scheduler v0.6

Reads hermes/schedules/compound_interest.yaml.
Runs on_startup / daily / weekly jobs.
Writes hermes/runtime/.scheduler_state.json for idempotency.
Never auto-trades. Never calls confirm_transaction. Never writes SQLite.

Usage: python -m hermes.runtime.scheduler
"""

import sys
import os
import json
import time
import signal
import yaml
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from hermes.runtime.config import ALERT_DIR
from hermes.runtime.run_once import run_daily_sample, run_anomaly_watch, run_weekly_review

# ── Constants ────────────────────────────────────────

SCHEDULE_PATH = Path("hermes/schedules/compound_interest.yaml")
STATE_PATH = Path("hermes/runtime/.scheduler_state.json")
POLL_INTERVAL = 30  # seconds

WEEKDAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}

# Tools that run_once supports directly
TOOL_TO_FN = {
    "daily_sample": run_daily_sample,
    "anomaly_watch": run_anomaly_watch,
    "weekly_review": run_weekly_review,
    "backup_db": None,  # handled specially
    "daily_startup_check": None,  # handled specially
}

# These are NEVER run by the scheduler
SKIP_MODES = {"manual", "human_confirm"}

running = True

# ── State file ──────────────────────────────────────

def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _job_done_today(state: dict, job_name: str, today_str: str) -> bool:
    return state.get(job_name, {}).get("last_run_date") == today_str


def _mark_job_done(state: dict, job_name: str, today_str: str, ts: str):
    state[job_name] = {"last_run_date": today_str, "last_run_time": ts}
    _save_state(state)


# ── Schedule parser ─────────────────────────────────

def load_schedule() -> dict:
    if not SCHEDULE_PATH.exists():
        raise FileNotFoundError(f"Schedule not found: {SCHEDULE_PATH}")
    with open(SCHEDULE_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_time(time_str: str) -> tuple[int, int]:
    """'20:30' → (20, 30)"""
    parts = time_str.split(":")
    return int(parts[0]), int(parts[1])


def _parse_weekly(day: str) -> int:
    """'Thursday' → 3, 'FRI' → 4"""
    return WEEKDAY_MAP.get(day.lower(), -1)


# ── Backup DB job ───────────────────────────────────

def _run_backup():
    """Run backup_db via tool_executor."""
    from hermes.runtime.tool_executor import execute_tool
    from hermes.runtime.tool_registry import load_registry
    load_registry()
    try:
        result = execute_tool("backup_db")
        if "error" in result:
            _write_alert("BACKUP_ERROR", f"Backup failed: {result['error']}")
        else:
            print(f"    [backup_db] ✅ {result.get('backup_path', '?')}")
    except Exception as e:
        _write_alert("BACKUP_ERROR", str(e))


def _run_startup_check():
    """Startup check: verify API is available."""
    from hermes.runtime.tool_executor import execute_tool
    from hermes.runtime.tool_registry import load_registry
    load_registry()
    try:
        result = execute_tool("health_check")
        if result.get("status") == "ok":
            print(f"    [startup_check] ✅ API v{result.get('version', '?')}")
        else:
            print(f"    [startup_check] ⚠️ {result}")
    except Exception as e:
        print(f"    [startup_check] ❌ {e}")


# ── Alert writer ────────────────────────────────────

def _write_alert(category: str, msg: str):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ALERT_DIR.mkdir(parents=True, exist_ok=True)
    path = ALERT_DIR / f"{category}_{ts}.md"
    path.write_text(
        f"# {category}\n\n{datetime.now().isoformat()}\n\n{msg}\n",
        encoding="utf-8",
    )
    print(f"    🚨 Alert: {path}")


# ── Job runner ──────────────────────────────────────

def _run_job(name: str, cfg: dict, state: dict, now: datetime):
    """Run a single job if it's time. Returns True if executed."""
    today_str = now.strftime("%Y-%m-%d")
    mode = cfg.get("mode", "automatic")

    if mode in SKIP_MODES:
        return False

    should_run = False
    schedule = cfg.get("schedule", "")

    # on_startup
    if schedule == "on_startup":
        if not _job_done_today(state, name, today_str):
            should_run = True
    # daily
    elif schedule.startswith("every day"):
        if not _job_done_today(state, name, today_str):
            h, m = _parse_time(schedule.replace("every day ", ""))
            if now.hour > h or (now.hour == h and now.minute >= m):
                should_run = True
    # weekly
    elif schedule.startswith("every"):
        if not _job_done_today(state, name, today_str):
            parts = schedule.split()
            if len(parts) >= 3:
                wday = _parse_weekly(parts[1])
                h, m = _parse_time(parts[2])
                if now.weekday() == wday and (now.hour > h or (now.hour == h and now.minute >= m)):
                    should_run = True

    if not should_run:
        return False

    print(f"[{now.strftime('%H:%M:%S')}] ▶ {name}")
    try:
        if name == "backup_db":
            _run_backup()
        elif name == "daily_startup_check":
            _run_startup_check()
        elif name in TOOL_TO_FN and TOOL_TO_FN[name]:
            TOOL_TO_FN[name]()
        else:
            print(f"    ⚠️ Unknown tool: {name}")
    except Exception as e:
        _write_alert(f"JOB_ERROR_{name}", str(e))

    _mark_job_done(state, name, today_str, now.strftime("%H:%M:%S"))
    return True


# ── Next job preview ────────────────────────────────

def _next_job_summary(schedule_cfg: dict, now: datetime) -> str:
    """Human-readable next job time."""
    parts = []
    for name, cfg in schedule_cfg.get("jobs", {}).items():
        mode = cfg.get("mode", "")
        if mode in SKIP_MODES:
            continue
        sched = cfg.get("schedule", "")
        if sched == "on_startup":
            continue
        if sched.startswith("every day"):
            h, m = _parse_time(sched.replace("every day ", ""))
            next_dt = now.replace(hour=h, minute=m, second=0)
            if next_dt <= now:
                next_dt += timedelta(days=1)
            parts.append(f"{name}={next_dt.strftime('%m/%d %H:%M')}")
        elif sched.startswith("every"):
            sp = sched.split()
            if len(sp) >= 3:
                wday = _parse_weekly(sp[1])
                h, m = _parse_time(sp[2])
                delta = (wday - now.weekday()) % 7
                if delta == 0 and now.hour * 60 + now.minute >= h * 60 + m:
                    delta = 7
                next_dt = (now + timedelta(days=delta)).replace(hour=h, minute=m, second=0)
                parts.append(f"{name}={next_dt.strftime('%m/%d %H:%M')}")
    return ", ".join(parts) if parts else "none"


# ── Main loop ──────────────────────────────────────

def _shutdown(sig, frame):
    global running
    print("\n🛑 Shutting down...")
    running = False


def main():
    global running
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print("=" * 60)
    print(" Hermes Scheduler v0.6")
    print(f" Schedule: {SCHEDULE_PATH}")
    print(f" State:    {STATE_PATH}")
    print(f" Alerts:   {ALERT_DIR}")
    print("=" * 60)

    schedule_cfg = load_schedule()
    jobs = schedule_cfg.get("jobs", {})
    state = _load_state()
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # Reset state on new day
    state_date = state.get("_date", "")
    if state_date != today_str:
        state = {"_date": today_str}
        _save_state(state)
        print(f"[{now.strftime('%H:%M:%S')}] 📅 New day: {today_str} — state reset")

    # Run on_startup jobs
    for name, cfg in jobs.items():
        if cfg.get("schedule") == "on_startup":
            _run_job(name, cfg, state, now)

    print(f"[{now.strftime('%H:%M:%S')}] 📋 Scheduler running")
    print(f"    Auto jobs: {[n for n, c in jobs.items() if c.get('mode') not in SKIP_MODES]}")
    print(f"    Skipped:    {[n for n, c in jobs.items() if c.get('mode') in SKIP_MODES]}")
    next_info = _next_job_summary(schedule_cfg, now)
    print(f"    Next:       {next_info or '(none pending)'}")
    print("    Ctrl+C to stop")
    print()

    while running:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        # Reset state on new day
        if state.get("_date") != today_str:
            state = {"_date": today_str}
            _save_state(state)

        any_ran = False
        for name, cfg in jobs.items():
            if _run_job(name, cfg, state, now):
                any_ran = True

        if any_ran:
            next_info = _next_job_summary(schedule_cfg, now)
            s = state.get("_date", "")
            print(f"[{now.strftime('%H:%M:%S')}] 💓 Next: {next_info}" if next_info else f"[{now.strftime('%H:%M:%S')}] 💓")

        time.sleep(POLL_INTERVAL)

    print("👋 Scheduler stopped.")


if __name__ == "__main__":
    main()
