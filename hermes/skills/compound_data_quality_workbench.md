# compound-data-quality-workbench

## trigger
"数据质量", "scan issues", "修复数据"

## commands
- GET /api/data-quality/summary
- POST /api/data-quality/scan
- POST /api/data-quality/issues/{id}/fix

## fixable
- NO_SNAPSHOT → 重新拉取快照
- STALE_DATA → 刷新源数据

## needs_human
- WEAK_PROXY → 需评估代理指数
- VALUATION_DATA_MISSING → 债券估值待开发

## forbidden
- 修改 recommended_amount / risk_guard
- 创建交易 / 扣减资金池
- 生成 mock 估值数据
