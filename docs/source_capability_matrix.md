# Source Capability Matrix v1.1.5

## Data Sources

| Source | Max Holdings | Coverage Level | Fields | Access |
|--------|-------------|----------------|--------|--------|
| AKShare (fund_portfolio_hold_em) | 10 | top10_only | 代码,名称,占净值%,持股数,市值 | ✅ Active |
| EastMoney (via AKShare) | 10 | top10_only | same as above | ✅ (same endpoint) |
| 天天基金 | N/A | unknown | 需HTML解析 | ❌ No API |
| 基金定期报告(PDF) | full | full_disclosure | 全年持股市值/占比 | ❌ Manual only |
| 基金半年报 | 50+ | top50 | 全部股票持仓 | ❌ PDF manual |
| SEC EDGAR / 内地披露平台 | full | full | 结构化 | ❌ Not applicable (QDII only) |

## Status: All 7 funds → top10_only

```
coverage_level: top10_only (highest available)
live_usable_scope: heavy_position_overlap_only
limitation: 仅前十大季度重仓，中尾部重叠无法计算

upgrade_path: 
  Best: 基金半年报/年报PDF解析 (6月/12月) → 50-100只完整持仓
  Medium: 天天基金HTML爬取 → ~50只
  None: 季度报告只有Top10
```

## Rule

top10_only 只能用于 heavy_position_overlap 判断。
top10_only 不单独触发实盘强降级。
industry_overlap 需要 industry_count >= 3 才参与 live。
