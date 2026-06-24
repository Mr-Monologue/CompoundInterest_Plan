# Runtime Operator Contract v0.9.6

## Rules
1. compoundctl is the ONLY execution entry point.
2. Backend READY does NOT equal Data READY.
3. PORT_CONFLICT must NOT show as READY.
4. Old project processes auto-release after fingerprint match.
5. Non-project processes MUST be blocked.
6. update-check: inspect only, never apply.
7. update-apply: must backup, test, build.
8. Strategy/risk/transaction/DB migration changes MUST be blocked.
9. NEVER auto-trade. NEVER auto-confirm transactions.
