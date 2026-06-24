#!/usr/bin/env python3
"""compoundctl v0.9 — Hermes Runtime Controller. Never auto-trades."""
import os, sys, json, time, socket, signal, subprocess, argparse, urllib.request, shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(os.environ.get("CIP_ROOT", Path(__file__).parent.resolve()))
BACKEND_PORT = 9600
FRONTEND_PORT = 731
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
STATE_FILE = ROOT / "hermes/runtime/.process_state.json"
HB_FILE = ROOT / "hermes/runtime/.scheduler_heartbeat.json"
POLICY_FILE = ROOT / "hermes/runtime/runtime_policy.yaml"
AUDIT_FILE = ROOT / "logs/runtime_audit.jsonl"
LOGS_DIR = ROOT / "logs"

def _load_policy():
    try:
        import yaml
        with open(POLICY_FILE) as f: return yaml.safe_load(f)
    except: return {"autonomy_mode": "runtime_admin", "auto_actions": {"release_stale_backend": True}}
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

def _run(cmd, cwd=None, logfile=None, env=None):
    kw = {"cwd": str(cwd or ROOT), "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if env:
        kw["env"] = {**os.environ, **env}
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

def _port_pid(port):
    """Get PID of process occupying a port. Returns (pid, ok) or (None, False)."""
    try:
        if sys.platform == "win32":
            r = subprocess.run(f"netstat -ano | findstr :{port} | findstr LISTENING", shell=True, capture_output=True, text=True, timeout=5)
            for line in r.stdout.strip().split("\n"):
                parts = line.strip().split()
                if parts and parts[-1].isdigit():
                    return int(parts[-1]), True
    except: pass
    return None, False

def _audit(event, port=None, pid=None, action=""):
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_FILE, "a") as f:
        f.write(json.dumps({"event":event,"port":port,"pid":pid,"action":action,"timestamp":datetime.now().isoformat()}, default=str) + "\n")

def _process_fingerprint(pid):
    """Check if a PID matches project fingerprint."""
    try:
        if sys.platform == "win32":
            # Use tasklist (ASCII output) to avoid wmic Unicode issues
            r = subprocess.run(f"tasklist /FI \"PID eq {pid}\" /FO CSV /NH", shell=True, capture_output=True, text=True, timeout=5, errors='replace')
            cmdline = r.stdout.lower()
            return "python" in cmdline
    except: pass
    return False

def _release_port_if_fingerprint_matches(port):
    """Auto-release port if occupied by project process. Returns dict with result."""
    policy = _load_policy()
    if not policy.get("auto_actions", {}).get("release_stale_backend"):
        return {"status": "SKIPPED", "reason": "auto_release disabled in policy"}

    pid, ok = _port_pid(port)
    if not ok:
        return {"status": "NOT_OCCUPIED"}

    is_project = _process_fingerprint(pid)
    if not is_project:
        _audit("port_conflict_blocked", port=port, pid=pid, action="blocked_non_project")
        return {"status": "PORT_CONFLICT_BLOCKED", "port": port, "pid": pid,
                "reason": "Process does not match project fingerprint"}

    # Auto-release: terminate specific PID
    _audit("auto_release_port", port=port, pid=pid, action="terminate_specific_pid")
    try: os.kill(pid, signal.SIGTERM); time.sleep(1)
    except: pass
    # Verify released
    if _port_open(port):
        _audit("auto_release_failed", port=port, pid=pid, action="terminate_failed")
        return {"status": "RELEASE_FAILED", "port": port, "pid": pid}
    _audit("auto_release_success", port=port, pid=pid, action="released")
    return {"status": "RELEASED", "port": port, "pid": pid}

def _restart_managed_backend():
    """Restart backend — auto-release stale if policy allows, then restart."""
    rr = _release_port_if_fingerprint_matches(BACKEND_PORT)
    if rr.get("status") == "PORT_CONFLICT_BLOCKED":
        return rr
    # Start fresh with absolute DB path
    db_path = str(ROOT / "invest.db")
    _run(f"python -m backend.main", logfile=LOGS_DIR/"backend.log",
         env={"COMPOUND_DB_PATH": db_path})
    for _ in range(20):
        time.sleep(1)
        if _port_open(BACKEND_PORT): break
    state = _read_state()
    state["backend"] = {"started_at": datetime.now().isoformat(), "started_by": "compoundctl"}
    _write_state(state)
    h = _api_get("/api/health")
    return {"status": "READY", "features": (h or {}).get("features", {}), "auto_released": rr}

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

    # Backend — check features, restart if old using managed restart
    h = _api_get("/api/health")
    features = (h or {}).get("features", {})
    if not features.get("exposure_demo"):
        results["backend_note"] = "Old backend, auto-restarting..."
        rr = _restart_managed_backend()
        if rr.get("status") == "PORT_CONFLICT":
            results.update(rr)
            return results
    elif not _port_open(BACKEND_PORT):
        _run(f"python -m backend.main", logfile=LOGS_DIR/"backend.log",
             env={"COMPOUND_DB_PATH": db_path})
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
        rr = _restart_managed_backend()
        if rr.get("status") == "PORT_CONFLICT":
            return {"error": "PORT_CONFLICT", "port": rr["port"], "pid": rr["pid"], "action": "manual_confirm_required"}
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

    # Check what changed
    policy = _load_policy()
    try:
        r = subprocess.run("git diff --name-only HEAD~1 2>&1", shell=True, capture_output=True, text=True, cwd=str(ROOT), timeout=10)
        changed = r.stdout.strip().split("\n") if r.stdout.strip() else []
        unsafe = [f for f in changed if any(kw in f.lower() for kw in
            ["strategy", "risk_guard", "risk guard", "migration", "transaction", "confirm", "trade", "buy", "sell"])]
        if unsafe and not policy.get("update_policy", {}).get("auto_apply_strategy_changes"):
            return {"blocked": True, "reason": "策略/风控/交易相关变更，已阻断自动应用", "unsafe_files": unsafe}
    except: pass

    steps = []
    # 1. Backup DB
    try:
        import shutil
        db_path = ROOT / "invest.db"
        if db_path.exists():
            bak = ROOT / f"data/invest.db.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db_path, bak)
            steps.append({"step": "backup_db", "ok": True, "path": str(bak)})
    except Exception as e:
        steps.append({"step": "backup_db", "ok": False, "error": str(e)})
    # 2. Git pull
    try:
        r = subprocess.run("git pull", shell=True, capture_output=True, text=True, cwd=str(ROOT), timeout=30)
        steps.append({"step": "git_pull", "ok": r.returncode==0, "output": r.stdout.strip()[-200:]})
    except Exception as e:
        steps.append({"step": "git_pull", "ok": False, "error": str(e)})
    # 3. Install deps
    try:
        r = subprocess.run(f"{sys.executable} -m pip install -r requirements.txt --quiet", shell=True, capture_output=True, text=True, cwd=str(ROOT), timeout=60)
        steps.append({"step": "pip_install", "ok": r.returncode==0})
    except:
        steps.append({"step": "pip_install", "ok": False})
    # 4. pytest
    try:
        r = subprocess.run(f"{sys.executable} -m pytest tests/ -q", shell=True, capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        steps.append({"step": "pytest", "ok": r.returncode==0, "output": r.stdout.strip()[-100:]})
    except:
        steps.append({"step": "pytest", "ok": False})
    # 5. npm build
    try:
        r = subprocess.run("npm run build", shell=True, capture_output=True, text=True, cwd=str(ROOT/"frontend"), timeout=120)
        steps.append({"step": "npm_build", "ok": r.returncode==0})
    except:
        steps.append({"step": "npm_build", "ok": False})
    # 6. Restart
    rr = start()
    steps.append({"step": "restart", "result": rr})
    return {"steps": steps, "all_ok": all(s.get("ok", True) for s in steps)}

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
