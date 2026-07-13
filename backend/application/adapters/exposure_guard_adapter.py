"""v2.1 Exposure Guard Adapter — batch apply, never increase amount."""
from sqlmodel import Session


def apply_exposure_guard_batch(candidates, session):
    """Apply exposure guard to all candidates at once. Can reduce/block, never increase."""
    try:
        from services.exposure_guard import apply_exposure_guard
        guard_input = []
        for c in candidates:
            guard_input.append({
                "fund_code": c["asset_code"],
                "candidate_amount": c.get("final_amount", c.get("candidate_amount", 0)) or 0,
                "action": c.get("candidate_action", "NO_ACTION"),
            })
        results = apply_exposure_guard(guard_input, session)
        if isinstance(results, dict) and "items" in results:
            results = results["items"]
        # Map results back
        for i, r in enumerate(results):
            if i < len(candidates):
                final = r.get("final_amount", candidates[i].get("final_amount"))
                candidates[i]["exposure_status"] = r.get("status", "ok")
                candidates[i]["exposure_reasons"] = r.get("reason", "")
                if r.get("blocked"):
                    candidates[i]["candidate_action"] = "REVIEW_REQUIRED"
                    candidates[i]["final_amount"] = None
                    candidates[i]["exposure_status"] = "BLOCKED"
                elif final is not None and final < (candidates[i].get("final_amount") or 0):
                    candidates[i]["final_amount"] = final  # can only decrease
                    candidates[i]["exposure_status"] = "REDUCED"
        return candidates
    except Exception as e:
        # Guard failure: mark all REVIEW_REQUIRED, don't silently pass
        for c in candidates:
            c["exposure_status"] = "GUARD_ERROR"
            c["exposure_reasons"] = f"guard failure: {str(e)[:200]}"
            if c.get("candidate_amount") and c["candidate_amount"] > 0:
                c["candidate_action"] = "REVIEW_REQUIRED"
        return candidates
