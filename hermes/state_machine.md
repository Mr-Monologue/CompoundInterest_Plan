# State Machines — Hermes Agent Runtime

## 1. Daily State Machine

```
                    ┌─────────┐
                    │  IDLE   │
                    └────┬────┘
                         │ schedule trigger or manual
                         ▼
                  ┌──────────────┐
                  │  CHECK_API   │
                  └──────┬───────┘
                         │ API up?
                    ┌────┴────┐
                    │ NO      │ YES
                    ▼         ▼
              ┌──────────┐  ┌──────────────────────┐
              │ API_ERROR │  │  RUN_DAILY_SAMPLE    │
              │ (alert)   │  │  POST /api/snapshot/ │
              └──────────┘  │  daily/run           │
                            └──────────┬───────────┘
                                       │
                                       ▼
                              ┌────────────────┐
                              │  AUDIT_RESULT  │
                              └───────┬────────┘
                                      │
                         ┌────────────┴────────────┐
                         │ action_allowed?         │
                    ┌────┴────┐              ┌─────┴─────┐
                    │ TRUE    │              │ FALSE     │
                    ▼         ▼              ▼           ▼
          ┌─────────────────┐        ┌──────────────────────┐
          │ WRITE_DAILY_    │        │ WRITE_BLOCKED_ALERT  │
          │ REPORT           │        │                      │
          │ (recommended_   │        │ ⛔ BLOCKED           │
          │  amount present)│        │ recommended_amount   │
          └────────┬────────┘        │ = null               │
                   │                 └──────────┬───────────┘
                   │                            │
                   └──────────┬─────────────────┘
                              ▼
                    ┌──────────────────┐
                    │ WAIT_USER_REVIEW │
                    │  (human reviews  │
                    │   daily report)  │
                    └──────────────────┘
```

**Rules:**
- BLOCKED state must NOT output buy amounts.
- `computed_amount` only goes into audit trace.
- `recommended_amount` is the only actionable amount.

---

## 2. Weekly State Machine

```
                    ┌─────────┐
                    │  IDLE   │
                    └────┬────┘
                         │ Friday trigger
                         ▼
                ┌──────────────────┐
                │ FETCH_WEEKLY_DATA│
                │ GET /api/reports/│
                │ weekly           │
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │ CHECK_DATA_      │
                │ QUALITY          │
                │ (source, trusted,│
                │  staleness)      │
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │ GENERATE_WEEKLY_ │
                │ SUMMARY          │
                │ (8 sections)     │
                └────────┬─────────┘
                         │
                    ┌────┴────┐
                    │ anomalies?
               ┌────┴────┐    │
               │ YES     │    │ NO
               ▼         │    ▼
        ┌──────────────┐│ ┌──────────────┐
        │MARK_NEEDS_   ││ │ WAIT_USER_   │
        │REVIEW        ││ │ REVIEW       │
        └──────┬───────┘│ └──────────────┘
               │         │
               └────┬────┘
                    ▼
            ┌──────────────┐
            │ WAIT_USER_   │
            │ REVIEW       │
            └──────────────┘
```

**Rules:**
- Must not promise returns.
- Must not predict market directions.
- All conclusions must cite API data fields.

---

## 3. Transaction State Machine

```
                    ┌────────────┐
                    │ NO_ACTION  │
                    └─────┬──────┘
                          │ user requests transaction
                          ▼
                   ┌────────────────┐
                   │ DRAFT_         │
                   │ TRANSACTION    │
                   │ (confirmed=    │
                   │  false)        │
                   └───────┬────────┘
                           │
                     ┌─────┴─────┐
                     │ risk_guard│
                     │ PASS?     │
                ┌────┴────┐      │
                │ NO      │      │ YES
                ▼         │      ▼
         ┌──────────┐    │ ┌──────────────────┐
         │ BLOCKED  │    │ │ WAIT_USER_       │
         │ (reject) │    │ │ CONFIRM          │
         └──────────┘    │ │ (user reviews    │
                         │ │  in GUI)         │
                         │ └────────┬─────────┘
                         │          │ user confirms
                         │          ▼
                         │ ┌──────────────────┐
                         │ │ CONFIRMATION_    │
                         │ │ RECEIVED         │
                         │ │ (confirmed=true, │
                         │ │  created_by=gui) │
                         │ └────────┬─────────┘
                         │          │
                         │          ▼
                         │ ┌──────────────────┐
                         │ │ RECORD_          │
                         │ │ TRANSACTION      │
                         │ │ POST /api/       │
                         │ │ transactions     │
                         │ └────────┬─────────┘
                         │          │
                         │          ▼
                         │ ┌──────────────────┐
                         │ │ WRITE_LEDGER     │
                         │ │ (+ pool_ledger   │
                         │ │  if from_pool)   │
                         │ └────────┬─────────┘
                         │          │
                         │          ▼
                         │ ┌──────────────────┐
                         │ │ WAIT_USER_REVIEW │
                         │ └──────────────────┘
```

**Rules:**
- Must NOT write confirmed transaction before WAIT_USER_CONFIRM.
- risk_guard FAIL → must NOT enter RECORD_TRANSACTION.
- recommended_amount=null → must NOT enter RECORD_TRANSACTION.
- Only `created_by=gui` for confirmed transactions.
