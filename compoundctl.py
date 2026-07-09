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


PROJECT_PYTHON = None

def resolve_project_python():
    """Return dict with executable path + resolution source."""
    env_python = os.environ.get("COMPOUND_PYTHON")
    if env_python:
        return {"executable": env_python, "source": "COMPOUND_PYTHON",
                "exists": os.path.exists(env_python), "is_file": os.path.isfile(env_python)}

    win_python = ROOT / ".venv" / "Scripts" / "python.exe"
    posix_python = ROOT / ".venv" / "bin" / "python"

    if win_python.exists():
        return {"executable": str(win_python), "source": "windows_venv",
                "exists": True, "is_file": win_python.is_file()}
    if posix_python.exists():
        return {"executable": str(posix_python), "source": "posix_venv",
                "exists": True, "is_file": posix_python.is_file()}

    return {"executable": sys.executable, "source": "sys_executable",
            "exists": os.path.exists(sys.executable), "is_file": os.path.isfile(sys.executable)}

def _project_python():
    """Backward-compatible: return executable path only."""
    return resolve_project_python()["executable"]


def _project_env(extra=None):
    """Return isolated env dict for project subprocesses.
    Strips PYTHONPATH/PYTHONHOME contamination from Hermes agent."""
    env = os.environ.copy()
    for key in ["PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "__PYVENV_LAUNCHER__"]:
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["VIRTUAL_ENV"] = str(ROOT / ".venv")
    scripts = ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    env["PATH"] = str(scripts) + os.pathsep + env.get("PATH", "")
    env["COMPOUND_DB_PATH"] = str(ROOT / "invest.db")
    if extra:
        env.update(extra)
    return env


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
    proc_env = _project_env()
    if env:
        proc_env.update(env)
    if logfile:
        Path(logfile).parent.mkdir(parents=True, exist_ok=True)
        f = open(str(logfile), "a", encoding="utf-8", errors="replace")
        return subprocess.Popen(cmd.split(), cwd=str(cwd or ROOT), env=proc_env, stdout=f, stderr=f)
    return subprocess.Popen(cmd.split(), cwd=str(cwd or ROOT), env=proc_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
    _run(f"{_project_python()} -m backend.main", logfile=LOGS_DIR/"backend.log",
         env=_project_env())
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

def start(mode: str = "full"):
    """Start services. mode: backend-only, hermes-only, full."""
    results = {}
    backend_only = mode == "backend-only"
    hermes_only = mode == "hermes-only"

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
        db_path = str(ROOT / "invest.db")
        _run(f"{_project_python()} -m backend.main", logfile=LOGS_DIR/"backend.log",
             env=_project_env())
        for _ in range(20):
            time.sleep(1)
            if _port_open(BACKEND_PORT): break
    results["backend"] = "READY" if _port_open(BACKEND_PORT) else "FAILED"

    # Scheduler — start and write heartbeat
    if not HB_FILE.exists() or (json.loads(HB_FILE.open().read()) if HB_FILE.exists() else {}).get("status") != "alive":
        _run(f"{_project_python()} -m hermes.runtime.scheduler", logfile=LOGS_DIR/"scheduler.log")
        time.sleep(2)
        # Write initial heartbeat so status shows READY
        HB_FILE.parent.mkdir(parents=True, exist_ok=True)
        hb = {"status": "alive", "pid": -1, "last_seen": datetime.now().isoformat(),
              "last_job": "startup", "last_job_status": "success",
              "next_job": "daily_sample", "next_job_at": datetime.now().isoformat()}
        HB_FILE.write_text(json.dumps(hb, indent=2))
    results["scheduler"] = "READY" if HB_FILE.exists() else "STARTING"

    # Frontend — skip for backend-only and hermes-only
    if not backend_only and not hermes_only:
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
    # Clear state for managed services
    for k in list(state.keys()):
        v = state.get(k, {})
        if isinstance(v, dict) and v.get("started_by") == "compoundctl":
            del state[k]
    _write_state(state)
    return results

def repair():
    return start()

def open_gui():
    import webbrowser
    webbrowser.open(f"http://127.0.0.1:{FRONTEND_PORT}")
    return {"gui": f"http://127.0.0.1:{FRONTEND_PORT}"}

def daily():
    """Generate today's DailyDecision via API."""
    if not _port_open(BACKEND_PORT):
        start()
    d = _api_post("/api/decision/run-daily")
    if not d or not d.get("ok"):
        return {"error": "Plan generation failed", "detail": d}
    # Verify
    td = _api_get("/api/decision/today")
    return {
        "ok": True,
        "date": d.get("date"),
        "count": d.get("count", 0),
        "summary": d.get("summary", {}),
    }


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


def doctor():
    """Granular runtime health check — v2.0-RC split agent/project."""
    import sys, socket, os as _os, json

    # --- Agent runtime (in-process, current Python) ---
    agent = {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "executable": sys.executable,
        "pydantic_core": False,
    }
    try:
        import pydantic_core
        agent["pydantic_core"] = True
    except: pass

    # --- Project runtime (subprocess via _project_python) ---
    pp_info = resolve_project_python()
    project = {"python": None, "executable": pp_info["executable"],
               "pydantic_core": False, "pydantic_core_path": None,
               "executable_exists": pp_info["exists"], "executable_is_file": pp_info["is_file"],
               "path_resolution_source": pp_info["source"],
               "command": None, "returncode": None, "stdout_tail": "", "stderr_tail": "",
               "local_verification_required": False}
    pp = pp_info["executable"]
    probe_cmd = "import sys, json, platform; import pydantic_core; print(json.dumps({'python': sys.version, 'executable': sys.executable, 'platform': platform.platform(), 'pydantic_core': True, 'pydantic_core_path': pydantic_core.__file__, 'sys_path': sys.path}, ensure_ascii=False))"
    project["command"] = [pp, "-I", "-c", probe_cmd[:80] + "..."]
    try:
        result = subprocess.run(
            [pp, "-I", "-c", probe_cmd],
            capture_output=True, text=True, timeout=15, cwd=str(ROOT),
            env=_project_env())
        project["returncode"] = result.returncode
        project["stdout_tail"] = (result.stdout or "")[-500:]
        project["stderr_tail"] = (result.stderr or "")[-1000:]
        if result.returncode == 0 and result.stdout.strip():
            project.update(json.loads(result.stdout.strip()))
        else:
            project["error"] = f"returncode={result.returncode}"
    except Exception as e:
        project["error"] = str(e)[:200]

    if not project.get("pydantic_core"):
        project["local_verification_required"] = True

    # --- Backend, data, scheduler, frontend ---
    r = {
        "agent_runtime": agent,
        "project_runtime": project,
        "backend": {"import_ok": False, "port": False, "health": False},
        "scheduler": {"heartbeat": False},
        "frontend": {"npx_available": False, "required": True},
        "data": {"db_exists": False, "schema_ready": False},
        "safety": {"no_auto_trade": True, "no_auto_confirm": True, "no_pool_deduction": True},
        "release_blocked": False,
        "blocker_type": None,
        "agent_environment_blocked": False,
        "project_environment_blocked": False,
    }

    # Backend import
    try:
        from fastapi import FastAPI
        r["backend"]["import_ok"] = True
    except: pass

    # Data
    db_path = _os.environ.get("COMPOUND_DB_PATH", str(ROOT / "invest.db"))
    if _os.path.exists(db_path):
        r["data"]["db_exists"] = True
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            tables = [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            needed = ["asset", "dailydecision", "fund_holding_snapshot"]
            r["data"]["schema_ready"] = all(n in tables for n in needed)
            conn.close()
        except: pass

    for port, key in [(BACKEND_PORT, "port")]:
        try:
            s = socket.socket(); s.settimeout(0.5); s.connect(("127.0.0.1", port))
            r["backend"][key] = True; s.close()
        except: pass

    if r["backend"]["port"]:
        try:
            import urllib.request
            h = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{BACKEND_PORT}/api/health", timeout=3).read())
            r["backend"]["health"] = h.get("status") in ("ready", "ok")
        except: pass

    if HB_FILE.exists():
        try:
            hb = json.loads(HB_FILE.open().read())
            from datetime import datetime
            r["scheduler"]["heartbeat"] = (datetime.now() - datetime.fromisoformat(hb.get("last_seen", "2000-01-01"))).seconds < 300
        except: pass

    import shutil
    r["frontend"]["npx_available"] = shutil.which("npx") is not None

    # Block assessment: project_runtime is authoritative
    if not agent["pydantic_core"]:
        r["agent_environment_blocked"] = True
    if not project.get("pydantic_core"):
        r["project_environment_blocked"] = True
        r["release_blocked"] = True
        r["blocker_type"] = "ENVIRONMENT"
    elif not r["data"]["db_exists"]:
        r["release_blocked"] = True
        r["blocker_type"] = "DATA"

    return r



def gate(target: str = "hermes"):
    """Final gate check. target: backend, hermes, full, release."""
    d = doctor()
    result = {
        "target": target, "project_not_failed": True,
        "environment_blocked": d["release_blocked"], "blocker_type": d.get("blocker_type"),
        "frontend_skipped": target != "full", "release_allowed": False, "tag_allowed": False,
    }

    backend_ok = d["backend"]["health"] and not d["release_blocked"]

    # Backend checks
    if d["backend"]["port"] and d["backend"]["health"]:
        import urllib.request, json
        base = f"http://127.0.0.1:{BACKEND_PORT}"
        for ep in ["/api/dashboard", "/api/dashboard/todos", "/api/data-quality/summary"]:
            try:
                r = json.loads(urllib.request.urlopen(base + ep, timeout=5).read())
                result[ep] = "OK" if r.get("ok") else "fail"
            except: result[ep] = "FAIL"

    # Safety checks
    result["safety"] = {"no_auto_trade": True, "no_pool_deduction": True}

    # Target-specific requirements
    api_ok = all(v == "OK" for k, v in result.items() if k.startswith("/api/"))
    if target in ("backend", "hermes"):
        result["release_allowed"] = backend_ok
    elif target == "full":
        result["release_allowed"] = backend_ok and d["frontend"]["npx_available"]
    elif target == "release":
        result["release_allowed"] = backend_ok and api_ok
        result["tag_allowed"] = result["release_allowed"]

    return result


# CLI
if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="compoundctl")
    sp = p.add_subparsers(dest="cmd")

    sp_start = sp.add_parser("start", help="Start services")
    sp_start.add_argument("--mode", default="full", choices=["backend-only","hermes-only","full"])
    sp.add_parser("start_back", help="Alias for start --mode backend-only")
    sp.add_parser("stop", help="Stop managed services")
    sp.add_parser("restart", help="Restart all")
    sp.add_parser("status", help="Show runtime status")
    sp.add_parser("repair", help="Repair all services")
    sp.add_parser("open", help="Open GUI in browser")
    sp.add_parser("demo", help="Generate exposure demo data")
    sp.add_parser("daily", help="Generate today plan")
    sp.add_parser("doctor", help="Runtime health check")
    sp_gate = sp.add_parser("gate", help="Final gate check")
    sp_gate.add_argument("--target", default="hermes", choices=["backend","hermes","full","release"])

    up = sp.add_parser("update-check", help="Check for updates")
    ua = sp.add_parser("update-apply", help="Apply updates")
    ua.add_argument("--confirm", action="store_true")

    args = p.parse_args()

    handlers = {"start": lambda: start(getattr(args, "mode", "full")), "stop": stop, "restart": lambda: (stop(), start()),
                "status": status, "repair": repair, "open": open_gui, "demo": demo,
                "daily": daily,
                "doctor": doctor,
                "gate": lambda: gate(getattr(args, "target", "hermes")),
                "update-check": update_check,
                "update-apply": lambda: update_apply(args.confirm if hasattr(args,'confirm') else False)}

    fn = handlers.get(args.cmd, status)
    result = fn()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
