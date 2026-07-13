# Data Contracts

## DailyDecision
- strategy_action: fixed_dca | dynamic_dca | observe | take_profit_watch | blocked
- decision_action: BUY | OBSERVE | WATCH | REVIEW_REQUIRED | BLOCKED | NO_ACTION
- exposure_status: TOP10_ONLY_READY | FULL_EXPOSURE_READY | DATA_MISSING

## WeeklyInvestmentPlan
- status: DRAFT → FROZEN → CONFIRMED → CLOSED
- FROZEN 后核心字段不可修改
- 重复创建同 week_start + config_id 幂等

## Amount Formats
- API 输出金额必须格式化为固定两位小数
- null → 不显示金额 (BLOCKED/AUDIT_ONLY)
- 0 → ¥0 (OBSERVE/WATCH)

## Data Quality
- 每个 plan item 必须有 data_quality_status
- BLOCKED item 可进入计划但不输出可执行金额
