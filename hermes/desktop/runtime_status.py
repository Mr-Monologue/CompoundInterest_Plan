"""runtime_status.py — Hermes runtime status for frontend display"""
import json, os, time
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(os.environ.get("CIP_ROOT", os.getcwd()))

def get_runtime_status():
    """Get current runtime status of all managed services."""
    try:
        from hermes.desktop.supervisor import status as svc_status
        statuses = svc_status()
    except:
        statuses = {"backend": "UNKNOWN", "frontend": "UNKNOWN", "scheduler": "UNKNOWN"}

    decision_ready = False
    hb_path = PROJECT_ROOT / "hermes/runtime/.scheduler_heartbeat.json"
    last_heartbeat = None
    if hb_path.exists():
        hb = json.loads(hb_path.open().read())
        last_heartbeat = hb.get("last_seen")

    return {
        "backend": statuses.get("backend", "UNKNOWN"),
        "frontend": statuses.get("frontend", "UNKNOWN"),
        "scheduler": statuses.get("scheduler", "UNKNOWN"),
        "decision_today_generated": decision_ready,
        "last_heartbeat": last_heartbeat,
        "checked_at": datetime.now().isoformat(),
    }
