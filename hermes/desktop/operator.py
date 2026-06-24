"""operator.py — Hermes Desktop Operator v0.9.2

All actions via compoundctl. NO manual taskkill/python/curl/git output.
Emergency troubleshooting only in docs/troubleshooting.md.
"""
import os, json, subprocess, sys
from pathlib import Path

ROOT = Path(os.environ.get("CIP_ROOT", os.getcwd()))

# Hard-ban keywords — if any response contains these, it's a bug
BANNED_KEYWORDS = ["taskkill /F /IM python.exe", "手动 git pull", "手动启动", "npx vite",
                   "curl -X POST", "你本机重启即可", "手动 curl", "python backend/main.py"]

ROOT = Path(os.environ.get("CIP_ROOT", os.getcwd()))

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


def sanitize_output(text):
    """Block manual command suggestions. Returns (clean, is_clean)."""
    blocked = ["taskkill", "git pull", "python backend/main.py", "npx vite",
               "curl -X POST", "手动启动", "手动重启", "你本机执行", "运行以下命令"]
    for kw in blocked:
        if kw.lower() in text.lower():
            return "该操作应由 compoundctl 执行。请说：修复投资系统 / 应用更新 / 打开 Demo 模式。", False
    return text, True
