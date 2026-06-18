# Value-DCA Strategy Framework — v0.8

> 核心-卫星价值定投增强系统

## 项目定位

CompoundInterestPlan 不是基金短线交易系统，不是自动交易系统。
它是**核心-卫星价值定投增强系统**。

## 策略层级

```
┌──────────────────────────────┐
│  7. 风控层 (risk_guard)      │ ← 决定是否展示金额
├──────────────────────────────┤
│  6. 资金层 (amount_policy)   │ ← recommended_amount
├──────────────────────────────┤
│  5. 4%触发层 (four_percent)  │ ← dry_run 实验模块
├──────────────────────────────┤
│  4. 价格层 (price_position)  │ ← MA200 dev_pct
├──────────────────────────────┤
│  3. 估值层 (valuation)       │ ← PE/PB分位 (v0.9)
├──────────────────────────────┤
│  2. 资产层 (thesis)          │ ← 投资逻辑状态
├──────────────────────────────┤
│  1. 数据层 (data)            │ ← 数据完整性与可信度
└──────────────────────────────┘
```

## 核心概念

### AssetRole (仓位角色)

| 角色 | 说明 |
|------|------|
| core | 核心仓位（宽基指数/优质混合） |
| satellite | 卫星仓位（行业/主题基金） |
| cash | 现金等价物 |
| watch_only | 仅观察 |

### ThesisStatus (投资逻辑)

| 状态 | 说明 |
|------|------|
| HOLD_OK | 逻辑成立 |
| WATCH | 加强观察 |
| STOP_ADD | 暂停加仓 |
| REVIEW_REQUIRED | 需重新评估 |

### ValuationState (估值状态 — v0.9 接入)

| 状态 | 说明 |
|------|------|
| cheap | 低估 |
| fair_low | 合理偏低 |
| fair | 合理 |
| fair_high | 合理偏高 |
| expensive | 偏高 |
| unknown | 未接入 |

### PricePosition (价格位置 — 基于 MA200)

| 位置 | dev_pct |
|------|---------|
| low_position | ≤ -10% |
| normal_position | -10%~+5% |
| high_position | > +5% |

### 4% 定投法 (实验模块，dry_run)

规则：
1. 仅用于指数基金或代理指数判断
2. 需要 valuation_state ∈ {cheap, fair_low}
3. 目标投入额分 10 份
4. 触发价 = 上次买入参考价 × 0.96
5. proxy_close ≤ 触发价 → triggered
6. 本轮不改变 recommended_amount

## 不做什么

- ❌ 不自动交易
- ❌ 不把基金当股票炒
- ❌ 不使用基金交易量/申购人数作为涨跌信号
- ❌ MA200 仅用于代理指数价格位置判定
- ❌ 4% 法不能变成无脑网格补仓
- ❌ GUI 是人工复核台，不得删除
