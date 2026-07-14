"""v2.1 Exposure Guard Adapter — production contract."""
from sqlmodel import Session


def apply_exposure_guard_batch(candidates, session):
    """Apply production exposure guard. Full input/output contract.
    On guard failure: mark all REVIEW_REQUIRED, don't silently pass."""
    try:
        from services.exposure_guard import apply_exposure_guard

        guard_input = []
        for c in candidates:
            guard_input.append({
                "fund_code": c["asset_code"],
                "fund_name": c.get("asset_code", ""),
                "asset_role": c.get("asset_role", "core"),
                "strategy_action": c.get("candidate_action", "NO_ACTION"),
                "system_status": c.get("risk_status", "PASS"),
                "recommended_amount": c.get("candidate_amount", 0) or 0,
                "candidate_amount": c.get("final_amount", c.get("candidate_amount", 0)) or 0,
                "dev_pct": 0.0,
            })

        results = apply_exposure_guard(guard_input, session)
        items = results.get("items", results) if isinstance(results, dict) else results
        if not isinstance(items, list):
            items = []

        for i, r in enumerate(items):
            if i >= len(candidates):
                break
            c = candidates[i]
            # Read from guard output
            final = r.get("recommended_amount", c.get("final_amount"))
            status = r.get("exposure_status", "ok")

            if r.get("downgrade_reason") and ("BLOCKED" in str(r["downgrade_reason"]).upper()):
                c["candidate_action"] = "BLOCKED"
                c["final_amount"] = None
                c["exposure_status"] = "BLOCKED"
            elif status in ("BLOCKED", "REVIEW_REQUIRED"):
                c["final_amount"] = None
                c["exposure_status"] = status
                c["candidate_action"] = "REVIEW_REQUIRED"
            elif final is not None and final < (c.get("final_amount") or 0):
                c["final_amount"] = final
                c["exposure_status"] = "REDUCED"
            else:
                c["exposure_status"] = "ok"

            c["exposure_reasons"] = r.get("exposure_reasons", r.get("downgrade_reason", ""))
            c["candidate_action"] = r.get("strategy_action", c.get("candidate_action"))

        return candidates

    except Exception as e:
        for c in candidates:
            c["exposure_status"] = "GUARD_ERROR"
            c["exposure_reasons"] = str(e)[:200]
            if (c.get("final_amount") or 0) > 0:
                c["candidate_action"] = "REVIEW_REQUIRED"
                c["final_amount"] = None
        return candidates
