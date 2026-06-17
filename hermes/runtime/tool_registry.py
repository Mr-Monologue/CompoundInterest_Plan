"""tool_registry.py — Load and query the tool registry YAML"""
import yaml
from pathlib import Path
from typing import Dict, Any, Optional


_registry: Optional[Dict[str, dict]] = None


def load_registry(yaml_path: Path = None) -> dict:
    """Load tools from compound_interest_tools.yaml. Cached after first load."""
    global _registry
    if _registry is not None:
        return _registry

    path = yaml_path or Path("hermes/tools/compound_interest_tools.yaml")
    if not path.exists():
        raise FileNotFoundError(f"Tool registry not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    tools = data.get("tools", [])
    _registry = {t["name"]: t for t in tools}
    return _registry


def get_tool(name: str) -> dict:
    """Get a single tool definition by name. Raises KeyError if unknown."""
    reg = load_registry()
    if name not in reg:
        raise KeyError(
            f"Tool '{name}' not registered. Available: {list(reg.keys())}"
        )
    return reg[name]


def list_tools() -> list:
    """Return all registered tool names."""
    return list(load_registry().keys())


def tool_allowed(name: str, context: dict = None) -> tuple[bool, str]:
    """Check if a tool can be executed given the current context.

    Returns (allowed: bool, reason: str).
    """
    tool = get_tool(name)
    forbidden = tool.get("forbidden_when", []) or []
    ctx = context or {}

    checks = {
        "risk_guard_fail": not ctx.get("risk_guard_passed", True),
        "action_allowed_false": not ctx.get("action_allowed", True),
        "recommended_amount_null": ctx.get("recommended_amount") is None,
        "source_mock": str(ctx.get("source", "")).lower() == "mock",
        "trusted_false": not ctx.get("trusted", True),
        "user_not_confirmed": not ctx.get("user_confirmed", False),
        "confirmed_without_user_approval": ctx.get("confirmed") and not ctx.get("user_confirmed", False),
        "created_by_hermes": str(ctx.get("created_by", "")).lower() == "hermes",
    }

    for condition in forbidden:
        if checks.get(condition, False):
            return False, f"forbidden_when: {condition}"

    return True, ""


def requires_token(name: str) -> bool:
    return get_tool(name).get("requires_token", False)


def is_transaction_related(name: str) -> bool:
    return get_tool(name).get("transaction_related", False)
