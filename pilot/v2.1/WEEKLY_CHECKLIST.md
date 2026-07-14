# Weekly Pilot Checklist

## Pre-Plan
- [ ] Market data fetched and fresh
- [ ] Data quality audit passed or documented
- [ ] `compoundctl doctor` clean

## Plan
- [ ] `POST /api/weekly-plans/build` → plan created
- [ ] All amounts verifiable in calculation_trace
- [ ] Budget split matches config (core/satellite)

## Execution
- [ ] User reviews each item
- [ ] User approves/skips/defers
- [ ] User executes on external platform
- [ ] `POST /api/weekly-plan-items/{id}/execution` records facts
- [ ] `POST /api/executions/{id}/reconcile` confirms

## Review
- [ ] `POST /api/weekly-reviews/generate`
- [ ] User reviews variances
- [ ] FollowUpActions completed
- [ ] `POST /api/weekly-reviews/{id}/close`

## Safety
- [ ] Transaction count matches executed items
- [ ] Pool balance unchanged
- [ ] Zero auto-trade, zero auto-confirm
