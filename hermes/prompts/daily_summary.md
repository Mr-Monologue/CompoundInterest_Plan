# Daily Summary Prompt — Hermes Agent

> 每日采样完成后，Hermes 使用此模板输出当日摘要。

---

## 输出格式

```
## 每日定投摘要 — {YYYY-MM-DD}

### 状态: {PASS | ⛔ BLOCKED}

| 字段 | 值 |
|------|-----|
| 基金代码 | {fund_code} |
| 基金净值 | {fund_nav} |
| 净值日期 | {fund_nav_date} |
| 代理指数代码 | {proxy_code} |
| 代理指数收盘价 | {proxy_close} |
| MA200 | {proxy_ma200} |
| MA200 偏离 | {dev_pct * 100}% |
| 数据源 | {data_source} |
| 可信 | {is_trusted} |
| risk_guard | {risk_guard_passed} |
| action_allowed | {action_allowed} |
| 建议金额 | {recommended_amount 或 null} |
| 准备金余额 | {reserve_after} |
```

---

## 分支逻辑

### 如果 action_allowed=true

```
## 每日定投摘要 — {YYYY-MM-DD}

### 状态: ✅ PASS

[表格]

### 人工复核建议
- 今日建议定投金额为 ¥{recommended_amount}，请人工确认后通过 GUI 执行。
- 准备金余额充足/需关注。

> ⚠️ 本建议仅基于系统计算，不构成投资建议。请根据个人情况决策。
```

### 如果 action_allowed=false

```
## 每日定投摘要 — {YYYY-MM-DD}

### 状态: ⛔ BLOCKED

| 字段 | 值 |
|------|-----|
| 基金代码 | 000083 |
| 基金净值 | 4.3050 |
| 净值日期 | 2025-08-29 |
| 代理指数代码 | 000932 |
| 代理指数收盘价 | 15150.00 |
| MA200 | 15100.25 |
| MA200 偏离 | 0.33% |
| 数据源 | Mock |
| 可信 | ❌ false |
| risk_guard | ❌ FAIL |
| action_allowed | false |
| 建议金额 | null |
| 准备金余额 | ¥632.81 |

### 阻断原因
- 数据源为 Mock，禁止生成正式建议
- 数据源为 Mock，不可用于实盘建议

### 审计详情 (calculation_trace)
| 字段 | 值 |
|------|-----|
| computed_amount | ¥192.50（仅供审计，不作为建议） |
| fixed_amount | ¥80.00 |
| dynamic_amount | ¥112.50 |
| reserve_before | ¥750.00 |
| reserve_after | ¥632.81 |

### 结论
> ⛔ 数据异常，需要人工复核。本次不输出买入金额。

### 人工复核建议
- 系统已自动阻断本次建议生成。
- Mock 数据不可用于实盘辅助。
- 请通过 GUI 点击「采样并保存」获取真实数据后重试。

> ⚠️ `computed_amount` 仅出现在 `calculation_trace` 中，不得出现在建议金额栏。
```

---

## 禁止事项

| 禁止 | 说明 |
|------|------|
| ❌ risk_guard FAIL 时输出买入金额 | `recommended_amount` 已是 null，不得绕过 |
| ❌ source=Mock 时输出买入金额 | mock 数据不可用于实盘 |
| ❌ 使用 `computed_amount` 作为建议 | `computed_amount` 仅供审计 |
| ❌ "必须买入" / "稳赚" / "一定回本" | 禁止任何承诺性表述 |
| ❌ 编造 API 未返回的数据 | 所有数值必须来自 API 返回字段 |
| ❌ 自动创建交易 | 交易必须由用户在 GUI 确认 |

---

## 数据来源

- 所有数值来自 `POST /api/snapshot/daily/run` 返回的 JSON
- `recommended_amount` 仅在 `action_allowed=true` 时有值
- `computed_amount` 存放于 `calculation_trace`，仅供审计
