"""tool_executor.py — Execute tools through FastAPI. Never writes SQLite directly."""
import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

from . import tool_registry
from .config import API_BASE, get_token


# Phase 2: tools that are permanently disabled
PHASE2_DISABLED = {"confirm_transaction"}


def execute_tool(name: str, params: dict = None, timeout: int = 60) -> Dict[str, Any]:
    """Execute a registered tool via FastAPI.

    Args:
        name: Tool name from the registry
        params: Query params (GET) or body (POST)
        timeout: HTTP timeout in seconds

    Returns:
        API response as dict

    Raises:
        KeyError: Unknown tool
        RuntimeError: Tool requires token but none configured
        RuntimeError: Tool is disabled in Phase 2
    """
    if name in PHASE2_DISABLED:
        raise RuntimeError(
            f"Tool '{name}' is DISABLED in Phase 2. "
            "Transaction confirmation must be done through the GUI."
        )

    tool = tool_registry.get_tool(name)
    method = tool["method"]
    endpoint = tool["endpoint"]
    needs_token = tool.get("requires_token", False)

    if needs_token:
        token = get_token()
        if not token:
            raise RuntimeError(
                f"Tool '{name}' requires X-Local-Token but none configured. "
                "Set CIP_API_TOKEN in .env"
            )

    url = f"{API_BASE}{endpoint}"
    data = None
    headers = {"Content-Type": "application/json"}

    if needs_token:
        headers["X-Local-Token"] = token

    if method == "GET" and params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    elif method == "POST":
        data = json.dumps(params or {}, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:1000]
        return {
            "error": f"HTTP {e.code}",
            "detail": body,
            "tool": name,
            "endpoint": endpoint,
        }
    except Exception as e:
        return {
            "error": str(e),
            "tool": name,
            "endpoint": endpoint,
        }


def is_safe_read(name: str) -> bool:
    """True if tool is a read-only GET operation."""
    tool = tool_registry.get_tool(name)
    return tool["method"] == "GET" and not tool.get("writes_db", False)
