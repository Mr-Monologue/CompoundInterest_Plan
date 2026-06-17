"""config.py — Runtime configuration loader"""
import os
from pathlib import Path


def _load_dotenv():
    """Simple .env loader, no external deps."""
    for env_path in (Path("data/.env"), Path(".env")):
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key not in os.environ:
                        os.environ[key] = val

_load_dotenv()

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8701")
_LOCAL_TOKEN = os.getenv("CIP_API_TOKEN", "")
REPORT_DIR = Path(os.getenv("HERMES_REPORT_DIR", "reports"))
ALERT_DIR = Path(os.getenv("HERMES_ALERT_DIR", "alerts"))
TOOLS_YAML = Path("hermes/tools/compound_interest_tools.yaml")
PROJECT_ROOT = Path(".").resolve()


def has_token() -> bool:
    return bool(_LOCAL_TOKEN)


def get_token() -> str:
    return _LOCAL_TOKEN


def require_token() -> None:
    if not has_token():
        raise RuntimeError(
            "CIP_API_TOKEN not set. Set it in .env file."
        )
