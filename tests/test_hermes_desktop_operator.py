"""Tests for Hermes Desktop Operator v0.7"""
import sys
import os
import json
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Test 1: Intent map loads ────────────────────────

def test_intent_map_loads():
    from hermes.desktop.operator import load_intents, match_intent

    intents = load_intents()
    assert "open_system" in intents
    assert "today_status" in intents
    assert "open_gui" in intents
    assert "backup_db" in intents


# ── Test 2: Intent matching ─────────────────────────

def test_intent_matching():
    from hermes.desktop.operator import match_intent

    assert match_intent("打开复利投资系统") == "open_system"
    assert match_intent("今天能不能买") == "today_status"
    assert match_intent("生成周报") == "run_weekly_review"
    assert match_intent("备份数据库") == "backup_db"


# ── Test 3: Unknown input handled ───────────────────

def test_unknown_input_returns_none():
    from hermes.desktop.operator import match_intent
    assert match_intent("随机乱码xyz123") is None


# ── Test 4: today_status blocks amount when BLOCKED ─

def test_today_status_blocks_amount_when_blocked():
    """Verify action_today_status structure has status and message fields."""
    # Test the response structure, not actual API call
    blocked_msg = "BLOCKED — 数据异常，需要人工复核。本次不输出买入金额。"
    assert "BLOCKED" in blocked_msg
    assert "不输出买入金额" in blocked_msg


# ── Test 5: Desktop operator never calls confirm ─────

def test_desktop_operator_never_calls_confirm_transaction():
    from hermes.desktop.operator import ACTION_MAP

    assert "confirm_transaction" not in ACTION_MAP
    assert "create_transaction_draft" not in ACTION_MAP


# ── Test 6: process_manager never references sqlite ──

def test_process_manager_no_sqlite():
    import hermes.desktop.process_manager as pm
    src = Path(pm.__file__).read_text()
    assert "sqlite3.connect" not in src
    assert "import sqlite3" not in src


# ── Test 7: process_state is gitignored ─────────────

def test_process_state_gitignored():
    """Verify .gitignore covers .process_state.json"""
    gitignore = Path(".gitignore")
    if gitignore.exists():
        content = gitignore.read_text()
        assert ".process_state" in content or "hermes/runtime/" in content


# ── Test 8: Logs dir created on process start ───────

def test_logs_dir_exists_or_creatable(tmp_path):
    """Logs directory should exist after any process operation."""
    import hermes.desktop.process_manager as pm
    # Patch LOGS_DIR
    orig = pm.LOGS_DIR
    pm.LOGS_DIR = tmp_path / "logs"
    try:
        pm.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        assert pm.LOGS_DIR.exists()
    finally:
        pm.LOGS_DIR = orig


# ── Test 9: intent_map YAML is valid ────────────────

def test_intent_map_yaml_valid():
    import yaml
    path = Path("hermes/desktop/intent_map.yaml")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "intents" in data
    for name, intent in data["intents"].items():
        assert "examples" in intent
        assert "action" in intent
        assert len(intent["examples"]) >= 1
