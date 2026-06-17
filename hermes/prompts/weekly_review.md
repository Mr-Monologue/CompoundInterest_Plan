# Weekly Review Prompt — Hermes Agent

> 每周复盘时，Hermes 使用此模板输出周度报告。

---

## 输出结构

```
# 周报 — {YYYY-WWW}

生成时间: {timestamp}
数据来源: GET /api/reports/weekly + GET /api/plan/latest + GET /api/snapshot/latest

---

## 1. 本周结论

{summary_paragraph}

---

## 2. 数据质量

| 指标 | 值 |
|------|-----|
| 数据源 | {proxy_source} |
| 可信 | {is_trusted} |
| 最新数据日期 | {nav_date} / {proxy_date} |
| 数据是否过旧 | {是/否} |

---

## 3. MA200 偏离变化

| 指标 | 值 |
|------|-----|
| 当前偏离 | {dev_pct * 100}% |
| 估值层级 | {low/mid/high} |
| 代理指数 | {proxy_close} |
| MA200 | {proxy_ma200} |
| 趋势 | {上升/下降/横盘} |

---

## 4. risk_guard 状态

| 指标 | 值 |
|------|-----|
| 通过 | {是/否} |
| action_allowed | {true/false} |
| recommended_amount | {¥XX.XX 或 null} |

---

## 5. 资金池变化

| 指标 | 值 |
|------|-----|
| 本周流入 | ¥{inflow} |
| 本周支出 | ¥{outflow} |
| 当前余额 | ¥{balance} |

---

## 6. 持仓收益变化

| 指标 | 值 |
|------|-----|
| 最新净值 | {nav} |
| 持仓市值 | ¥{market_value} |
| 未实现盈亏 | ¥{unrealized_pnl} ({unrealized_pct}%) |

---

## 7. 实际交易 vs 系统建议

| 日期 | 建议金额 | 实际执行 | 差异 |
|------|---------|---------|------|
| ... | ¥XX.XX | ¥XX.XX | ±XX.XX |

（如无实际交易记录，标注"待人工填写"）

---

## 8. 异常与人工复核项

{列出本周 anomalies，或 "无异常"}

---

## 9. 下周观察点

- 关注 MA200 趋势方向
- 关注准备金余额
- 关注数据源稳定性
- {其他基于 API 数据的观察}

> 本报告由 Hermes Runtime 自动生成，所有数据来自 API 返回。不构成投资建议。
```

---

## 禁止事项

| 禁止 | 说明 |
|------|------|
| ❌ 承诺收益 | 不得出现"必然上涨""稳赚""一定回本" |
| ❌ 预测涨跌 | 不得出现"下周必涨/必跌" |
| ❌ 编造数据 | 所有数值必须引用 API 返回字段 |
| ❌ risk_guard FAIL 时输出买入金额 | BLOCKED 时只输出 null |
| ❌ 使用 computed_amount | 只能引用 recommended_amount |
| ❌ 自动创建交易 | 周报只读，不写交易 |

---

## 数据来源

- `GET /api/reports/weekly?days=7` → narrative, total_amount
- `GET /api/plan/latest?fund_code=000083` → action_allowed, recommended_amount, dev_pct
- `GET /api/snapshot/latest?fund_code=000083` → nav, proxy_close, proxy_ma200
- `GET /api/pool/ledger?fund_code=000083` → pool entries
