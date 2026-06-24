"""operator.py — Hermes Desktop Operator v0.9
All actions via compoundctl. Never manual taskkill/python/curl."""
import os, json, subprocess
from pathlib import Path

ROOT = Path(os.environ.get("CIP_ROOT", os.getcwd()))
CTL = sys.executable + " " + str(ROOT / "compoundctl.py") if "sys" in dir() else str(ROOT / "compoundctl.py")

def _run(action):
    import sys
    ctl = sys.executable + " " + str(ROOT / "compoundctl.py")
    r = subprocess.run(f"{ctl} {action}", shell=True, capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    try: return json.loads(r.stdout)
    except: return {"raw": r.stdout, "err": r.stderr}

def action_open_system():
    s = _run("start")
    st = _run("status")
    _run("open")
    return {"services": s, "status": st, "gui": "http://127.0.0.1:731"}

def action_today_status():
    return _run("status")

def action_demo():
    s = _run("start")
    d = _run("demo")
    _run("open")
    return {"demo": d, "services": s}

def action_update_check():
    return _run("update-check")

def action_repair():
    return _run("repair")

def action_stop():
    return _run("stop")

def action_status():
    return _run("status")

# Intent → function mapping
ACTIONS = {
    "open_system": action_open_system,
    "today_status": action_today_status,
    "demo": action_demo,
    "update_check": action_update_check,
    "repair": action_repair,
    "stop_system": action_stop,
    "status": action_status,
}
