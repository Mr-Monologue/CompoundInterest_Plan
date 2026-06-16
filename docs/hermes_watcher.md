# Hermes Watcher — 本地守护进程

> 不写 SQLite，不创建交易，不修改代码。只调用 FastAPI 统一入口，生成报告和警报。

## 快速开始

### 1. 配置 .env

在项目根目录创建 `.env`（或 `data/.env`）：

```ini
API_BASE=http://127.0.0.1:8701
CIP_API_TOKEN=your-local-token

# 调度时间（可选）
HERMES_WATCHER_DAILY_TIME=20:30
HERMES_WATCHER_ANOMALY_TIME=20:40
HERMES_WATCHER_WEEKLY_DAY=THU
HERMES_WATCHER_WEEKLY_TIME=21:00

# 自动补写（默认 false）
HERMES_WATCHER_AUTO_CATCHUP=false
```

### 2. 启动

#### Windows

双击 `run_hermes_watcher.bat`

或者：

```powershell
python scripts/hermes_watcher.py
```

### 3. 安全停止

按 `Ctrl+C` 优雅退出。

## 任务调度

| 时间 | 任务 | API | 输出 |
|------|------|-----|------|
| 每天 20:30 | 每日采样 | `POST /api/snapshot/daily/run` | `reports/daily/YYYY-MM-DD.md` |
| 每天 20:40 | 异常检查 | `GET /api/plan/latest` | `alerts/YYYY-MM-DD_ANOMALY.md`（仅异常时） |
| 每四 21:00 | 周报 | `GET /api/reports/weekly` | `reports/weekly/YYYY-WW.md` |
| 每 30 分钟 | 心跳 | - | 控制台输出 |

## 行为说明

### 启动时

1. 检查 API 健康状态（`GET /api/health`）
2. 检查今天是否已有采样
   - 无采样 → 提示用户可手动执行
   - `AUTO_CATCHUP=true` → 自动触发补写
3. 启动调度器和心跳线程

### 每日采样 (20:30)

- 调用 `POST /api/snapshot/daily/run`
- `action_allowed=true` → 写 `reports/daily/` + 控制台 PASS
- `action_allowed=false` → 写 `reports/daily/` + `alerts/XX_BLOCKED.md` + 控制台 BLOCKED
- **不自动创建交易**

### 异常检查 (20:40)

检测以下异常时写 `alerts/XX_ANOMALY.md`：
- source=Mock
- trusted=false
- risk_guard_passed=false
- action_allowed=false
- BLOCKED 状态下 recommended_amount 非 null
- nav 异常
- ma200 异常
- |dev_pct| > 50%
- API token 错误
- 数据日期超过 3 天

**只提醒，不修代码，不写交易。**

### 周报 (每周四 21:00)

生成 `reports/weekly/YYYY-WW.md`，包含 8 个章节。

**禁止输出**：必然上涨、一定回本、稳赚、未经过 risk_guard 的买入建议。

### 心跳

每 30 分钟输出一次：`💓 alive. Next: daily=... weekly=...`

不频繁请求 API。

## 输出目录结构

```
reports/
├── daily/
│   └── 2025-01-15.md          # 每日采样报告
└── weekly/
    └── 2025-W03.md            # 周报

alerts/
├── 2025-01-15_BLOCKED.md      # 风险阻断警告
├── 2025-01-15_ANOMALY.md      # 异常检测报告
└── API_ERROR_20250115.md      # API 错误
```

## 设计原则

- ❌ 不直接写 SQLite
- ❌ 不调用 POST /api/transactions
- ❌ 不修改任何源代码
- ✅ 所有写操作通过 API + X-Local-Token
- ✅ 幂等：每日采样自带幂等键，重复调用不重复写入
- ✅ 所有 HTTP 请求带 timeout
- ✅ 请求失败写 alerts 而不静默

## 环境变量参考

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `API_BASE` | `http://127.0.0.1:8701` | FastAPI 地址 |
| `CIP_API_TOKEN` | `local-dev-token-change-me` | API 写操作 Token |
| `HERMES_WATCHER_DAILY_TIME` | `20:30` | 每日采样时间 |
| `HERMES_WATCHER_ANOMALY_TIME` | `20:40` | 异常检查时间 |
| `HERMES_WATCHER_WEEKLY_DAY` | `THU` | 周报星期 |
| `HERMES_WATCHER_WEEKLY_TIME` | `21:00` | 周报时间 |
| `HERMES_WATCHER_AUTO_CATCHUP` | `false` | 自动补写缺失的采样 |
