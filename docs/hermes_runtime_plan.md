# Hermes Agent Runtime — 运行编排层架构

> Hermes 是运行编排层，不直接操作数据，不自动交易。

---

## 架构层级

```
┌─────────────────────────────────────────┐
│        Hermes Agent Runtime             │
│  (编排层: 调度 → 工具调用 → 结果审计)     │
├─────────────────────────────────────────┤
│        Tool Registry                    │
│  (工具注册: YAML 定义 → 映射到 API)      │
├─────────────────────────────────────────┤
│        FastAPI (port 8701)              │
│  (工具接口层: REST 端点, X-Local-Token)  │
├─────────────────────────────────────────┤
│        api_service                      │
│  (唯一写入口: 幂等, risk_guard, 审计)    │
├──────────────┬──────────────────────────┤
│  risk_guard  │     accounting           │
│  (风控闸门)   │     (确定性金额计算)      │
├──────────────┴──────────────────────────┤
│              SQLite DB                  │
│           (唯一事实源)                    │
└─────────────────────────────────────────┘
                    ▲
                    │ 人工交互
              ┌─────┴─────┐
              │    GUI    │
              │ (人工复核台)│
              │ port 8501 │
              └───────────┘
```

---

## 各层职责

### Hermes Agent Runtime（编排层）

- 读取 `hermes/schedules/` 调度配置
- 通过 Tool Registry 调用工具
- 审计所有 API 返回结果
- 生成 daily/weekly 摘要
- **不直接写 DB**
- **不自动交易**

### Tool Registry（工具注册）

- 定义工具名称、端点、权限
- 定义 `forbidden_when` 条件
- 定义 input/output contract
- 未来可映射到 MCP tools

### FastAPI（工具接口层）

- 对外暴露 REST API
- GET 端点：无需 token
- POST 端点：需要 `X-Local-Token`
- CORS 仅允许 localhost
- DEBUG 模式控制 `/docs`

### api_service（唯一写入口）

- 所有写操作汇聚于此
- 幂等键防重复写入
- `created_by` 追踪来源
- 自动建表（不 DROP TABLE）

### risk_guard（风控闸门）

- Mock 数据拦截
- NAV/MA200/dev_pct 异常检测
- `action_allowed` 判定
- 失败时 `recommended_amount = null`

### accounting（确定性金额计算）

- Decimal 精度
- 支付宝口径
- 金额 2 位，净值 4 位

### SQLite DB（唯一事实源）

- `data/trend.db`
- 所有业务数据持久化于此
- Hermes/GUI/任何入口都不得绕过 api_service 直接写

### GUI（人工复核台）

- Streamlit, port 8501
- 展示采样结果、交易管理、资金池
- 风险阻断时显示 BLOCKED
- **不直接写 DB**

---

## Hermes 约束速查

| 行为 | 允许 |
|------|:----:|
| 直接写 SQLite | ❌ |
| 绕过 api_service | ❌ |
| 自动交易 | ❌ |
| 自动确认 | ❌ |
| risk_guard FAIL 时输出买入 | ❌ |
| 编造行情/数据 | ❌ |
| 承诺收益 | ❌ |
| 删除 GUI | ❌ |
| 调用 GET 端点 | ✅ |
| 调用 POST 端点（带 token） | ✅ |
| 创建交易草稿（confirmed=false） | ✅ |
| 输出 BLOCKED + 原因 | ✅ |
| 生成 daily/weekly 报告 | ✅ |
| 修改代码（用户要求 + dev mode） | ✅ |

---

## 未来扩展

### MCP 集成

Tool Registry 的 YAML 定义可映射为 MCP tools：
- `name` → tool name
- `input_contract` → `inputSchema`
- `endpoint` + `method` → HTTP request

### Hermes 原生 Scheduler

如果 Hermes 未来内置 cron scheduler，直接读取 `hermes/schedules/compound_interest.yaml` 即可调度。当前由 Hermes Watcher (`scripts/hermes_watcher.py`) 承担薄 runtime 角色。
