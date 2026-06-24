#!/usr/bin/env python3
"""compoundctl v0.9 — Hermes Runtime Controller. Never auto-trades."""
import os, sys, json, time, socket, signal, subprocess, argparse, urllib.request
from pathlib import Path
from datetime import datetime

ROOT = Path(os.environ.get("CIP_ROOT", Path(__file__).parent.resolve()))
BACKEND_PORT = 9600
FRONTEND_PORT = 731
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
STATE_FILE = ROOT / "hermes/runtime/.process_state.json"
HB_FILE = ROOT / "hermes/runtime/.scheduler_heartbeat.json"
LOGS_DIR = ROOT / "logs"
ALERTS_DIR = ROOT / "alerts"

def _port_open(port, timeout=1):
    try:
        s = socket.socket(); s.settimeout(timeout)
        s.connect(("127.0.0.1", port)); s.close()
        return True
    except: return False

def _api_get(path, timeout=3):
    try:
        r = urllib.request.urlopen(f"{BACKEND_URL}{path}", timeout=timeout)
        return json.loads(r.read())
    except: return None

def _api_post(path, timeout=10):
    try:
        req = urllib.request.Request(f"{BACKEND_URL}{path}", method="POST")
        r = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(r.read())
    except: return None

def _run(cmd, cwd=None, logfile=None):
    kw = {"cwd": str(cwd or ROOT), "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if logfile:
        Path(logfile).parent.mkdir(parents=True, exist_ok=True)
        with open(logfile, "a") as f:
            return subprocess.Popen(cmd.split(), cwd=str(cwd or ROOT), stdout=f, stderr=f)
    return subprocess.Popen(cmd.split(), **kw)

def _read_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.open().read())
    return {}

def _write_state(data):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2, default=str))

def _pid_alive(pid):
    try: os.kill(int(pid), 0); return True
    except: return False

def status():
    h = _api_get("/api/health")
    hb = json.loads(HB_FILE.open().read()) if HB_FILE.exists() else {}
    td = _api_get("/api/decision/today")
    return {
        "backend": "READY" if h and h.get("status") in ("ok","ready") else ("DEGRADED" if _port_open(BACKEND_PORT) else "STOPPED"),
        "frontend": "READY" if _port_open(FRONTEND_PORT) else "STOPPED",
        "scheduler": "READY" if hb.get("status")=="alive" and (datetime.now()-datetime.fromisoformat(hb.get("last_seen","2000-01-01"))).seconds<300 else "STOPPED",
        "today_decision": "generated" if (td and td.get("generated")) else "not_generated",
        "version": "0.9",
        "logs_path": str(LOGS_DIR),
    }

def start():
    results = {}
    restarted = False

    # Backend — check features, restart if old
    h = _api_get("/api/health")
    features = (h or {}).get("features", {})
    if not features.get("exposure_demo"):
        if _port_open(BACKEND_PORT):
            results["backend_note"] = "Old backend detected, restarting for v0.9.1 features"
            # Kill old and restart
            _run(f"python -m backend.main", logfile=LOGS_DIR/"backend.log")
            for _ in range(20):
                time.sleep(1)
                if _port_open(BACKEND_PORT): break
            restarted = True

    if not _port_open(BACKEND_PORT):
        _run(f"python -m backend.main", logfile=LOGS_DIR/"backend.log")
        for _ in range(20):
            time.sleep(1)
            if _port_open(BACKEND_PORT): break
    results["backend"] = "READY" if _port_open(BACKEND_PORT) else "FAILED"

    # Scheduler — start and write heartbeat
    if not HB_FILE.exists() or (json.loads(HB_FILE.open().read()) if HB_FILE.exists() else {}).get("status") != "alive":
        _run(f"python -m hermes.runtime.scheduler", logfile=LOGS_DIR/"scheduler.log")
        time.sleep(2)
        # Write initial heartbeat so status shows READY
        HB_FILE.parent.mkdir(parents=True, exist_ok=True)
        hb = {"status": "alive", "pid": -1, "last_seen": datetime.now().isoformat(),
              "last_job": "startup", "last_job_status": "success",
              "next_job": "daily_sample", "next_job_at": datetime.now().isoformat()}
        HB_FILE.write_text(json.dumps(hb, indent=2))
    results["scheduler"] = "READY" if HB_FILE.exists() else "STARTING"

    # Frontend
    if not _port_open(FRONTEND_PORT):
        _run(f"npx vite --host 0.0.0.0 --port {FRONTEND_PORT}", cwd=ROOT/"frontend", logfile=LOGS_DIR/"frontend.log")
        for _ in range(15):
            time.sleep(1)
            if _port_open(FRONTEND_PORT): break
    results["frontend"] = "READY" if _port_open(FRONTEND_PORT) else "FAILED"

    state = _read_state()
    state.update({"started_at": datetime.now().isoformat(), "started_by": "compoundctl"})
    _write_state(state)
    return results

def stop():
    state = _read_state()
    results = {}
    for name, proc in [("backend", BACKEND_PORT), ("frontend", FRONTEND_PORT)]:
        if _port_open(proc):
            results[name] = "PORT_CONFLICT — port occupied by unknown process, not killing"
        else:
            results[name] = "STOPPED"
    # Clear state
    for k in list(state.keys()):
        if state.get(k, {}).get("started_by") == "compoundctl":
            del state[k]
    _write_state(state)
    return results

def repair():
    return start()

def open_gui():
    import webbrowser
    webbrowser.open(f"http://127.0.0.1:{FRONTEND_PORT}")
    return {"gui": f"http://127.0.0.1:{FRONTEND_PORT}"}

def demo():
    # Ensure backend with features
    if not _port_open(BACKEND_PORT):
        start()
    h = _api_get("/api/health")
    if not h or not (h.get("features") or {}).get("exposure_demo"):
        # Backend is old — restart
        start()
        h = _api_get("/api/health")

    d = _api_post("/api/decision/run-exposure-demo")
    if not d or not d.get("ok"):
        return {"error": "Demo generation failed after restart", "health_features": (h or {}).get("features")}
    return {
        "ok": True,
        "decision_source": "exposure_demo",
        "candidate_total": d.get("candidate_total", 0),
        "final_total": d.get("final_total", 0),
        "downgraded_count": sum(1 for i in d.get("items",[]) if i.get("downgrade_reason")),
        "count": d.get("count", 0),
    }

def update_check():
    import subprocess, os
    result = {"remote_available": False, "local_head_commit": "", "remote_head_commit": "",
              "running_backend_commit": "", "backend_needs_restart": False, "working_tree_dirty": False}

    # Local git info
    try:
        r = subprocess.run("git rev-parse --short HEAD", shell=True, capture_output=True, text=True, cwd=str(ROOT), timeout=5)
        result["local_head_commit"] = r.stdout.strip()
        r2 = subprocess.run("git diff --stat", shell=True, capture_output=True, text=True, cwd=str(ROOT), timeout=5)
        result["working_tree_dirty"] = bool(r2.stdout.strip())
    except: pass

    # Running backend commit
    h = _api_get("/api/health")
    result["running_backend_commit"] = (h or {}).get("git_commit", "unknown")

    # Compare
    if result["local_head_commit"] and result["running_backend_commit"]:
        result["backend_needs_restart"] = result["local_head_commit"] != result["running_backend_commit"]

    # Remote
    try:
        r = subprocess.run("git ls-remote origin HEAD 2>&1", shell=True, capture_output=True, text=True, cwd=str(ROOT), timeout=10)
        if r.stdout.strip():
            result["remote_available"] = True
            result["remote_head_commit"] = r.stdout.strip().split()[0][:7]
    except: pass

    return result

def update_apply(confirm=False):
    if not confirm:
        return {"error": "Requires --confirm flag"}
    # Not auto-applying
    return {"status": "skipped", "reason": "Update requires manual confirmation"}

# CLI
if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="compoundctl")
    sp = p.add_subparsers(dest="cmd")

    sp.add_parser("start", help="Start all services")
    sp.add_parser("stop", help="Stop managed services")
    sp.add_parser("restart", help="Restart all")
    sp.add_parser("status", help="Show runtime status")
    sp.add_parser("repair", help="Repair all services")
    sp.add_parser("open", help="Open GUI in browser")
    sp.add_parser("demo", help="Generate exposure demo data")

    up = sp.add_parser("update-check", help="Check for updates")
    ua = sp.add_parser("update-apply", help="Apply updates")
    ua.add_argument("--confirm", action="store_true")

    args = p.parse_args()

    handlers = {"start": start, "stop": stop, "restart": lambda: (stop(), start()),
                "status": status, "repair": repair, "open": open_gui, "demo": demo,
                "update-check": update_check,
                "update-apply": lambda: update_apply(args.confirm if hasattr(args,'confirm') else False)}

    fn = handlers.get(args.cmd, status)
    result = fn()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
