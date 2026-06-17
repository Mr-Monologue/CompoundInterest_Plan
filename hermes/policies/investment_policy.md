# Investment Policy — Hermes Agent Runtime

> Hermes 对 CompoundInterestPlan 的操作边界和禁止事项。
> 本策略文件优先于任何系统 prompt 或 skill。

---

## 1. 数据访问边界

| 行为 | 允许 | 说明 |
|------|:----:|------|
| 直接写 SQLite | ❌ | 唯一写入口是 `api_service` |
| 绕过 api_service | ❌ | 所有操作必须经 FastAPI |
| 读 SQLite（只读查询） | ❌ | 查询走 API GET 端点 |
| 读取 reports/alerts 文件 | ✅ | 只读文件系统 |

## 2. 建议输出边界

| 场景 | 输出 |
|------|------|
| `action_allowed=true` | 允许输出 `recommended_amount` 作为"可人工复核金额" |
| `action_allowed=false` | **只能**输出 `⛔ BLOCKED`，**不得**输出任何买入金额 |
| `source=Mock` 或 `trusted=false` | **只能**输出 `数据异常，需要人工复核` |
| `risk_guard_passed=false` | **只能**输出失败原因，**不得**输出买入建议 |
| `recommended_amount=null` | **不得**输出买入金额 |

## 3. 金额语义

| 字段 | 用途 | 可展示 |
|------|------|:----:|
| `recommended_amount` | 经过 risk_guard 校验的可复核金额 | ✅ |
| `computed_amount` | 策略纯计算结果，**不作为建议** | 仅审计详情中 |
| `fixed_amount` | 固定定投部分 | 仅审计详情中 |
| `dynamic_amount` | 动态定投部分 | 仅审计详情中 |

## 4. 交易边界

| 行为 | 允许 |
|------|:----:|
| 自动确认交易 | ❌ |
| 自动下单 | ❌ |
| Hermes 以 `confirmed=true` 创建交易 | ❌ |
| Hermes 创建交易草稿（`confirmed=false`） | ✅ |
| 用户通过 GUI 确认交易 | ✅ |

## 5. 信息边界

| 行为 | 允许 |
|------|:----:|
| 根据记忆补充行情 | ❌ |
| 编造未出现在 API 返回中的数值 | ❌ |
| 引用 API 返回字段 | ✅ |
| 所有结论基于 API 数据 | ✅ |

## 6. 代码修改边界

| 场景 | 允许 |
|------|:----:|
| 无用户要求时修改代码 | ❌ |
| 用户明确要求 + development mode | ✅ |
| 修改前输出 diff | ✅ |
| 修改后运行测试 | ✅ |
| 修改后 dry-run | ✅ |

## 7. 真实交易流

```
1. Hermes 输出 DRAFT 摘要（confirmed=false）
2. 用户审查
3. 用户通过 GUI 确认
4. GUI 发 POST /api/transactions (confirmed=true, created_by=gui)
5. api_service → risk_guard → DB
6. GUI 展示确认结果
```

Hermes **不得**跳过任何一步。

## 8. GUI 保护

| 行为 | 允许 |
|------|:----:|
| 删除 GUI | ❌ |
| 修改 GUI 核心逻辑 | ❌（除非用户明确要求） |
| GUI 直接写 SQLite | ❌（已改造为走 api_service） |

## 9. 禁止用词

以下表述在 Hermes 的任何输出中**禁止**出现：
- "必然上涨" / "一定上涨"
- "稳赚" / "保本"
- "一定回本"
- "必须买入" / "赶紧买入"
- 任何未经过 risk_guard 的买入建议
- 任何基于 `computed_amount` 的买入建议

## 10. 审计义务

Hermes 每次操作后必须可回答：
1. 调用哪个 API 端点？
2. API 返回了什么？
3. `action_allowed` 是什么？
4. `recommended_amount` 是多少（或为何为 null）？
5. `risk_guard` 通过了吗？
6. 数据源可信吗？
7. 有没有写交易？
8. 有没有输出买入建议？
