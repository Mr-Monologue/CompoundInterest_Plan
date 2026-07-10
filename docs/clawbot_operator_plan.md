# Clawbot / TG Operator Plan

## Read-only Commands (no human confirm needed)
- /status → compoundctl status
- /today → GET /api/decision/today
- /weekly → GET /api/weekly-review
- /data-quality → GET /api/data-quality/summary
- /gate → compoundctl gate --target hermes
- /handoff → latest handoff report

## Human Confirm Required
- /restart → compoundctl start --mode hermes-only (needs confirm)
- /run-daily → POST /api/decision/run-daily (needs confirm)
- /fix {id} → POST /api/data-quality/issues/{id}/fix (needs confirm)

## Permanently Forbidden
- /buy, /sell, /redeem, /trade
- /modify-amount, /set-final
- /override-risk-guard
- /deduct-pool, /confirm-transaction
- /auto-trade

## TG Integration Plan
1. Hermes receives TG message → extracts command
2. Maps command to compoundctl/API
3. Read-only: returns result directly
4. Requires confirm: returns result + "确认执行?"
5. Forbidden: returns "🚫 禁止: 不自动交易"
