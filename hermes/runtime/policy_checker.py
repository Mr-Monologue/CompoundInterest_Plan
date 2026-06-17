"""policy_checker.py — Enforce investment policy on API results."""

from typing import Dict, Any


def check_policy(result: Dict[str, Any]) -> Dict[str, Any]:
    """Check a daily_sample API result against investment policy.

    Returns:
        {
            "status": "PASS" | "BLOCKED" | "ANOMALY",
            "action_allowed": bool,
            "recommended_amount": float | None,
            "errors": [str],
            "warnings": [str],
            "safe_to_display_amount": bool,
        }
    """
    errors = []
    warnings = []

    action_allowed = result.get("action_allowed", False)
    recommended = result.get("recommended_amount")
    source = str(result.get("data_source", "")).lower()
    trusted = result.get("is_trusted", True)
    risk_guard = result.get("risk_guard_passed", True)
    trace = result.get("calculation_trace", {})
    computed = trace.get("computed_amount") if trace else None

    # ── Critical checks → BLOCKED ──

    if not risk_guard:
        errors.append("risk_guard failed")
    if source == "mock":
        errors.append("source is Mock (untrusted)")
    if not trusted:
        errors.append("data is not trusted")
    if not action_allowed:
        errors.append("action_allowed is false")

    # ── P0 anomaly: BLOCKED but amount present ──

    if not action_allowed and recommended is not None:
        errors.append(
            "P0 ANOMALY: action_allowed=false but recommended_amount is not null. "
            "This is a data integrity issue."
        )

    # ── Warnings ──

    if computed is not None and recommended is not None and computed != recommended:
        warnings.append(
            f"computed_amount ({computed}) != recommended_amount ({recommended}). "
            "This may indicate filtering was applied."
        )

    # ── Determine status ──

    if errors:
        status = "BLOCKED"
    elif warnings:
        status = "ANOMALY"
    else:
        status = "PASS"

    safe = status == "PASS" and recommended is not None

    return {
        "status": status,
        "action_allowed": action_allowed,
        "recommended_amount": recommended,
        "errors": errors,
        "warnings": warnings,
        "safe_to_display_amount": safe,
    }


def quick_check(result: Dict[str, Any]) -> bool:
    """Quick pass/fail: True if safe to display. False otherwise."""
    return check_policy(result)["safe_to_display_amount"]
