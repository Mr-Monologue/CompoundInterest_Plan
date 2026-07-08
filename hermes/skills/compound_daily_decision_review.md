# compound-daily-decision-review

## trigger
"今日计划", "生成今日计划", "run-daily"

## actions
- BUY → 人工复核后去平台买入 → 回系统标记已完成
- OBSERVE → 记录观察
- WATCH → 重点关注, 加入观察记录
- REVIEW_REQUIRED → 必须查看原因, 可手动覆盖
- BLOCKED → 查看阻断原因, 不可交易
- NO_ACTION → 折叠显示

## safety
- 不自动交易
- AI 不决定金额
- 只有 BUY+已完成 才允许资金池扣减
