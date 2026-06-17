"""process_manager.py — Local process lifecycle management for CIP desktop.

Manages: API server, Scheduler, GUI (Streamlit).
Never starts confirm_transaction. Never writes SQLite directly.
Writes PID state to hermes/runtime/.process_state.json.
Writes logs to logs/api.log, logs/scheduler.log, logs/gui.log.
"""

import os
import sys
import json
import socket
import signal
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# ── Paths ──────────────────────────────────────────

PROJECT_ROOT = Path(os.getenv("CIP_PROJECT_ROOT", ".")).resolve()
STATE_FILE = PROJECT_ROOT / "hermes" / "runtime" / ".process_state.json"
LOGS_DIR = PROJECT_ROOT / "logs"
PYTHON = sys.executable

# ── PID state ──────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"managed_pids": {}, "started_at": None}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _is_pid_running(pid: int) -> bool:
    """Check if a process with given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _port_in_use(port: int) -> bool:
    """Check if localhost:port is already listening."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except (socket.error, OSError):
        return False


def _start_process(name: str, cmd: list, log_name: str) -> Optional[int]:
    """Start a subprocess, write log, return PID. Returns None on failure."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / log_name

    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"\n--- {name} started at {datetime.now().isoformat()} ---\n")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
            return proc.pid
        except Exception as e:
            log_file.write(f"ERROR: {e}\n")
            return None


# ── API ────────────────────────────────────────────

def check_api_running() -> bool:
    return _port_in_use(8701)


def start_api() -> bool:
    if check_api_running():
        return True
    pid = _start_process(
        "API",
        [PYTHON, "-m", "src.app.api", "--host", "127.0.0.1", "--port", "8701"],
        "api.log",
    )
    if pid:
        state = _load_state()
        state["managed_pids"]["api"] = pid
        state["started_at"] = state["started_at"] or datetime.now().isoformat()
        _save_state(state)
        return True
    return False


# ── Scheduler ──────────────────────────────────────

def check_scheduler_running() -> bool:
    state = _load_state()
    pid = state.get("managed_pids", {}).get("scheduler")
    return pid is not None and _is_pid_running(pid)


def start_scheduler() -> bool:
    if check_scheduler_running():
        return True
    pid = _start_process(
        "Scheduler",
        [PYTHON, "-m", "hermes.runtime.scheduler"],
        "scheduler.log",
    )
    if pid:
        state = _load_state()
        state["managed_pids"]["scheduler"] = pid
        state["started_at"] = state["started_at"] or datetime.now().isoformat()
        _save_state(state)
        return True
    return False


# ── GUI ────────────────────────────────────────────

def check_gui_running() -> bool:
    return _port_in_use(8501)


def open_gui() -> bool:
    if check_gui_running():
        return True
    # Try run_gui.py first, fall back to streamlit run
    if (PROJECT_ROOT / "run_gui.py").exists():
        cmd = [PYTHON, "run_gui.py"]
    else:
        cmd = [PYTHON, "-m", "streamlit", "run", "src/app/ui/gui.py",
               "--server.port", "8501", "--server.headless", "true"]

    pid = _start_process("GUI", cmd, "gui.log")
    if pid:
        state = _load_state()
        state["managed_pids"]["gui"] = pid
        state["started_at"] = state["started_at"] or datetime.now().isoformat()
        _save_state(state)
        return True
    return False


# ── Reports / Alerts ───────────────────────────────

def open_reports_dir() -> Path:
    d = PROJECT_ROOT / "reports"
    if not d.exists():
        d.mkdir(parents=True)
    return d


def open_alerts_dir() -> Path:
    d = PROJECT_ROOT / "alerts"
    if not d.exists():
        d.mkdir(parents=True)
    return d


# ── Stop ───────────────────────────────────────────

def stop_managed_processes() -> List[str]:
    """Stop all managed processes. Returns list of stopped process names."""
    state = _load_state()
    stopped = []
    for name, pid in list(state.get("managed_pids", {}).items()):
        if pid and _is_pid_running(pid):
            try:
                if os.name == "nt":
                    os.kill(pid, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGTERM)
                stopped.append(name)
            except OSError:
                pass
    state["managed_pids"] = {}
    _save_state(state)
    return stopped


# ── Status ─────────────────────────────────────────

def status() -> dict:
    """Return full system status."""
    return {
        "api_running": check_api_running(),
        "scheduler_running": check_scheduler_running(),
        "gui_running": check_gui_running(),
        "api_port": 8701,
        "gui_port": 8501,
        "gui_url": "http://localhost:8501",
        "logs_dir": str(LOGS_DIR),
        "reports_dir": str(open_reports_dir()),
        "alerts_dir": str(open_alerts_dir()),
        "managed_pids": _load_state().get("managed_pids", {}),
    }
