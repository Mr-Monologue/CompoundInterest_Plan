# compound-autonomous-operator

## trigger
Auto: system startup, every 15min health check
Manual: compoundctl start/stop/status/gate

## auto_allowed
- Start backend + scheduler (--mode hermes-only)
- Health check + gate
- Auto-restart stale/crashed processes
- Data quality scan (read-only from GET)
- Daily/weekly report generation
- Dashboard/todos generation
- Notify user via TG/webhook

## auto_forbidden
- 下单, 赎回, 买入, 卖出
- 修改 recommended_amount / final_amount
- 修改 risk_guard / exposure_guard
- 自动确认用户决策 (executed/reviewed/overridden)
- 扣减资金池
- 写真实交易
- 创建 Transaction 记录

## human_confirm_required
- BUY → executed
- REVIEW_REQUIRED → reviewed
- BLOCKED → acknowledged
- 用户 override decision_action
- Pool deduction after executed

## APIs
- GET /api/dashboard/todos
- GET /api/data-quality/summary
- GET /api/weekly-review
- POST /api/data-quality/scan
- POST /api/data-quality/issues/{id}/fix

## failure_handoff
- ENVIRONMENT_BLOCKED → operator_health.json
- BACKEND_DOWN → auto restart attempt → log to operator_health.log
