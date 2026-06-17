"""Tests for Hermes Scheduler v0.6"""
import sys
import os
import json
import tempfile
from pathlib import Path
from datetime import datetime
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Test 1: Load schedule ───────────────────────────

def test_scheduler_loads_schedule():
    from hermes.runtime.scheduler import load_schedule

    cfg = load_schedule()
    assert "jobs" in cfg
    jobs = cfg["jobs"]
    assert "daily_sample" in jobs
    assert "anomaly_watch" in jobs
    assert "weekly_review" in jobs
    assert "backup_db" in jobs
    assert "transaction_confirm" in jobs


# ── Test 2: Skip manual-only jobs ────────────────────

def test_scheduler_skips_manual_only_job():
    from hermes.runtime.scheduler import SKIP_MODES

    # transaction_confirm has mode="human_confirm"
    assert "human_confirm" in SKIP_MODES
    assert "manual" in SKIP_MODES

    # Verify it's in the schedule with the right mode
    from hermes.runtime.scheduler import load_schedule
    cfg = load_schedule()
    tc = cfg["jobs"]["transaction_confirm"]
    assert tc["mode"] in SKIP_MODES


# ── Test 3: on_startup runs once ────────────────────

def test_scheduler_runs_on_startup_once():
    from hermes.runtime.scheduler import _job_done_today, _mark_job_done

    today = "2025-01-15"
    state = {}

    assert not _job_done_today(state, "startup_check", today)
    _mark_job_done(state, "startup_check", today, "09:00:00")
    assert _job_done_today(state, "startup_check", today)


# ── Test 4: No repeat same daily job ─────────────────

def test_scheduler_does_not_repeat_same_daily_job():
    from hermes.runtime.scheduler import _job_done_today, _mark_job_done

    today = "2025-01-15"
    state = {}

    assert not _job_done_today(state, "daily_sample", today)
    _mark_job_done(state, "daily_sample", today, "20:30:00")
    assert _job_done_today(state, "daily_sample", today)

    # Next day: should allow
    tomorrow = "2025-01-16"
    assert not _job_done_today(state, "daily_sample", tomorrow)


# ── Test 5: Uses run_once functions ──────────────────

def test_scheduler_uses_run_once():
    from hermes.runtime.scheduler import TOOL_TO_FN
    from hermes.runtime.run_once import run_daily_sample, run_anomaly_watch, run_weekly_review

    assert TOOL_TO_FN["daily_sample"] is run_daily_sample
    assert TOOL_TO_FN["anomaly_watch"] is run_anomaly_watch
    assert TOOL_TO_FN["weekly_review"] is run_weekly_review


# ── Test 6: Never calls confirm_transaction ──────────

def test_scheduler_never_calls_confirm_transaction():
    from hermes.runtime.scheduler import TOOL_TO_FN, SKIP_MODES
    from hermes.runtime.tool_executor import PHASE2_DISABLED

    # confirm_transaction not in TOOL_TO_FN
    assert "confirm_transaction" not in TOOL_TO_FN

    # mode is "human_confirm" → skipped
    from hermes.runtime.scheduler import load_schedule
    cfg = load_schedule()
    tc = cfg["jobs"]["transaction_confirm"]
    assert tc["mode"] in SKIP_MODES


# ── Extra: state file round-trip ─────────────────────

def test_state_file_round_trip(tmp_path):
    from hermes.runtime.scheduler import _load_state, _save_state, _job_done_today, _mark_job_done, STATE_PATH

    # Patch STATE_PATH temporarily
    import hermes.runtime.scheduler as sched
    orig = sched.STATE_PATH
    sched.STATE_PATH = tmp_path / "test_state.json"
    try:
        state = _load_state()
        assert state == {}
        _mark_job_done(state, "daily_sample", "2025-01-15", "20:30:00")
        state2 = _load_state()
        assert state2["daily_sample"]["last_run_date"] == "2025-01-15"
    finally:
        sched.STATE_PATH = orig


# ── Extra: backup_db and startup_check handled ────────

def test_backup_and_startup_are_handled():
    from hermes.runtime.scheduler import TOOL_TO_FN
    # backup_db and daily_startup_check have their own handlers (not in TOOL_TO_FN as callable)
    # This is fine — they're handled by _run_backup and _run_startup_check
    assert "backup_db" in TOOL_TO_FN  # key exists even if value is None
    assert "daily_startup_check" in TOOL_TO_FN
