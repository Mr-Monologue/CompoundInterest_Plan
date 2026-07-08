# compound-investment-safety-audit

## trigger
"安全审计", "final gate", "release check"

## invariants
- no_auto_trade = true
- recommended_amount unchanged
- risk_guard unchanged
- valuation does not modify amount
- Top10-only does not force amount change

## api
- GET /api/dashboard
- GET /api/dashboard/todos
- GET /api/data-quality/summary
- GET /api/decision/today

## failure
- AUDIT_FAIL → no tag, no release push
- BLOCKED → Runtime Failure Protocol
