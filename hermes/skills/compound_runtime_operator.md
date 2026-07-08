# compound-runtime-operator

## trigger
"启动投资系统", "重启系统", "修复系统", "compoundctl start/restart/repair"

## commands
- `compoundctl start --mode full` — full stack
- `compoundctl start --mode backend-only` — backend only, no frontend
- `compoundctl start --mode hermes-only` — backend + scheduler, no frontend
- `compoundctl status` — runtime health
- `compoundctl doctor` — granular checks
- `compoundctl gate --target hermes` — final gate
- `compoundctl gate --target release` — release gate

## forbidden
- git pull, taskkill, python backend/main.py, npx, curl
- 修改 recommended_amount
- 修改 risk_guard
- 自动交易, 自动确认交易

## human_confirm_required
- BUY + executed → pool deduction
- REVIEW_REQUIRED override
- BLOCKED acknowledged

## failure_handoff
- ENVIRONMENT_BLOCKED → Runtime Failure Protocol
- PORT_CONFLICT → 非项目进程阻断
