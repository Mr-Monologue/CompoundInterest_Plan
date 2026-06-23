"""supervisor.py — Hermes Runtime Supervisor v0.8.5
Detect, start, stop, restart backend/frontend/scheduler.
Never kills non-Hermes processes. Never auto-trades.
"""
import os, json, time, socket, signal, subprocess, sys, yaml
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(os.environ.get("CIP_ROOT", os.getcwd()))
STATE_FILE = PROJECT_ROOT / "hermes/runtime/.process_state.json"
REGISTRY_FILE = Path(__file__).parent / "service_registry.yaml"
ALERTS_DIR = PROJECT_ROOT / "alerts"
MAX_RESTARTS = 3
RESTART_WINDOW = timedelta(minutes=10)

STATE_READY = "READY"
STATE_STOPPED = "STOPPED"
STATE_FAILED = "FAILED"
STATE_PORT_CONFLICT = "PORT_CONFLICT"
STATE_STALE_PID = "STALE_PID"


def load_service_registry():
    with open(REGISTRY_FILE) as f:
        return yaml.safe_load(f)["services"]


def read_process_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def write_process_state(data):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def check_port(port):
    s = socket.socket(); s.settimeout(1)
    try: s.connect(("127.0.0.1", port)); s.close(); return True
    except: return False


def check_pid(pid):
    try: os.kill(pid, 0); return True
    except: return False


def check_health(url, timeout=3):
    import urllib.request
    try:
        r = urllib.request.urlopen(url, timeout=timeout)
        return json.loads(r.read())
    except: return None


def status():
    registry = load_service_registry()
    state = read_process_state()
    result = {}
    for name, svc in registry.items():
        ps = state.get(name, {})
        p = svc.get("port")
        pid = ps.get("pid")
        alive = pid and check_pid(pid)
        port_ok = p and check_port(p)

        if not alive:
            result[name] = STATE_STOPPED
        elif svc["type"] == "http" and p:
            health = check_health(svc["health_url"])
            result[name] = STATE_READY if health and health.get("status") in ("ok", "ready") else STATE_STALE_PID
        elif svc["type"] == "heartbeat":
            hb_path = PROJECT_ROOT / svc["heartbeat_path"]
            if hb_path.exists():
                hb = json.loads(hb_path.open().read())
                last = datetime.fromisoformat(hb.get("last_seen", "2000-01-01"))
                result[name] = STATE_READY if (datetime.now() - last).total_seconds() < 300 else STATE_STALE_PID
            else:
                result[name] = STATE_STOPPED
        else:
            result[name] = STATE_READY if alive else STATE_STOPPED
    return result


def start_service(name):
    registry = load_service_registry()
    svc = registry[name]
    state = read_process_state()

    if svc.get("port") and check_port(svc["port"]):
        ps = state.get(name, {})
        if ps.get("started_by") == "hermes_supervisor":
            return {"status": STATE_READY}
        return {"status": STATE_PORT_CONFLICT, "reason": f"Port {svc['port']} occupied by non-Hermes process"}

    cwd = PROJECT_ROOT if svc["cwd"] == "." else PROJECT_ROOT / svc["cwd"]
    log_file = PROJECT_ROOT / svc["log_path"]
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a") as lf:
        proc = subprocess.Popen(svc["command"].split(), cwd=str(cwd), stdout=lf, stderr=lf)
    state[name] = {
        "pid": proc.pid, "command": svc["command"], "cwd": str(cwd),
        "port": svc.get("port"), "health_url": svc.get("health_url"),
        "started_at": datetime.now().isoformat(), "started_by": "hermes_supervisor",
        "log_path": str(log_file), "last_status": "STARTING", "last_check_at": "",
        "restart_count": 0, "last_restart": ""
    }
    write_process_state(state)
    return {"status": "STARTING", "pid": proc.pid}


def stop_service(name):
    state = read_process_state()
    ps = state.get(name, {})
    if not ps or ps.get("started_by") != "hermes_supervisor":
        return {"status": "UNKNOWN_OWNER", "reason": "Not managed by Hermes"}
    pid = ps.get("pid")
    if pid and check_pid(pid):
        os.kill(pid, signal.SIGTERM)
    del state[name]
    write_process_state(state)
    return {"status": STATE_STOPPED}


def restart_service(name):
    rs = state.get(name, {}).get("restart_count", 0)
    lr = state.get(name, {}).get("last_restart", "")
    if lr and (datetime.now() - datetime.fromisoformat(lr)) < RESTART_WINDOW:
        if rs >= MAX_RESTARTS:
            return {"status": STATE_FAILED, "reason": f"Max restarts ({MAX_RESTARTS}) in {RESTART_WINDOW}"}

    stop_service(name)
    result = start_service(name)
    state = read_process_state()
    state[name]["restart_count"] = rs + 1
    state[name]["last_restart"] = datetime.now().isoformat()
    write_process_state(state)
    return result


def ensure_service(name):
    s = status().get(name, STATE_STOPPED)
    if s != STATE_READY:
        return start_service(name)
    return {"status": STATE_READY}


def ensure_all():
    results = {}
    for name in ["backend", "scheduler", "frontend"]:
        r = ensure_service(name)
        results[name] = r["status"]
        if name == "backend" and r["status"] == "STARTING":
            for _ in range(30):
                time.sleep(1)
                h = check_health(load_service_registry()[name]["health_url"])
                if h: break
        elif name == "frontend" and r["status"] == "STARTING":
            for _ in range(15):
                time.sleep(1)
                if check_port(731): break
    return results


def repair():
    s = status()
    results = {}
    for name, st in s.items():
        if st != STATE_READY:
            results[name] = restart_service(name)["status"]
        else:
            results[name] = STATE_READY
    return results


def stop_all_managed():
    state = read_process_state()
    for name in list(state.keys()):
        stop_service(name)


def open_gui():
    import webbrowser
    webbrowser.open("http://127.0.0.1:731")


if __name__ == "__main__":
    st = status()
    print("=== Hermes Supervisor Status ===")
    for name, s in st.items():
        icon = {"READY":"✅","STOPPED":"⛔","FAILED":"❌","PORT_CONFLICT":"⚠️"}.get(s,"❓")
        print(f"{icon} {name}: {s}")
