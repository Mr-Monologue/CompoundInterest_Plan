# Strategy Constitution

## 投资哲学
1. 长期持有优质资产，不做短期择时
2. 低估多买，高估少买，极端高估停止
3. 分散配置，不all-in单一主题/行业
4. 人工复核所有动作，Agent 只提供建议和解释

## 定投规则
- 每周预算 200 元
- MA200 阈值：-10% 触发多买，+5% 触发少买
- 同主题最多 1 只基金可操作
- 行业暴露 >30% 停止动态 DCA

## 不可变约束
- no_auto_trade
- no_auto_confirm
- no_pool_deduction (without user confirm)
- 永不静默修改 recommended_amount
- 永不静默修改 risk_guard/exposure_guard
