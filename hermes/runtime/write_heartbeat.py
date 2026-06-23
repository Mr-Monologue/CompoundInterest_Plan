"""Write scheduler heartbeat JSON. Called by scheduler every 30s."""
import json, os, time
from pathlib import Path
from datetime import datetime

HB_PATH = Path(__file__).parent / ".scheduler_heartbeat.json"

def write_heartbeat(pid=None, last_job="", next_job="", next_job_at=""):
    hb = {
        "status": "alive",
        "pid": pid or os.getpid(),
        "last_seen": datetime.now().isoformat(),
        "last_job": last_job,
        "last_job_status": "success",
        "next_job": next_job,
        "next_job_at": next_job_at,
    }
    with open(HB_PATH, "w") as f:
        json.dump(hb, f, indent=2)

if __name__ == "__main__":
    write_heartbeat()
