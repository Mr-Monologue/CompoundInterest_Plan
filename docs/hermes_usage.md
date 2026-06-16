# Hermes Agent 接入规范

> Hermes 调用 CompoundInterestPlan 的统一入口和约束。
> 版本: v2.0

## 架构原则

```
Hermes ──→ FastAPI (port 8701) ──→ api_service ──→ risk_guard ──→ SQLite
GUI    ──→ api_service ──→ risk_guard ──→ SQLite
```

- **api_service 是唯一写入口**
- Hermes **禁止**直接写 SQLite
- Hermes **禁止**绕过 risk_guard
- Hermes 所有写操作前**必须输出确认摘要**

## 启动 API 服务器

```bash
# 安装依赖
pip install fastapi uvicorn

# 启动
python -m src.app.api --port 8701

# 或
uvicorn src.app.api:app --host 127.0.0.1 --port 8701
```

API 文档: http://127.0.0.1:8701/docs

## API 端点

### 每日采样

```
POST /api/snapshot/daily/run
Body: {"created_by": "hermes", "force": false}
```

幂等：同一基金同一天重复调用不重复写入。

### 查询最新快照

```
GET /api/snapshot/latest?fund_code=000083
```

### 查询最新计划

```
GET /api/plan/latest?fund_code=000083
```

### 交易录入 ⚠️

```
POST /api/transactions
Body: {
    "fund_code": "000083",
    "date": "2025-01-15",
    "tx_type": "BUY",
    "amount": 80.0,
    "from_pool": false,
    "note": "固定定投",
    "created_by": "hermes",
    "confirmed": true    ← 必须为 true，否则返回 409
}
```

**重要**: `created_by="hermes"` 且 `confirmed=false` 时，API 返回 409 并要求确认。
Hermes 在调用前必须输出确认摘要给用户。

### 删除交易

```
DELETE /api/transactions/{id}
```

from_pool 交易会自动退款。

### 资金池入金

```
POST /api/pool/deposit
Body: {
    "fund_code": "000083",
    "amount": 120.0,
    "note": "每周准备金流入",
    "created_by": "hermes"
}
```

### 资金池调整

```
POST /api/pool/adjust
Body: {
    "fund_code": "000083",
    "amount": -10.0,
    "note": "纠正前期错误",
    "created_by": "manual"
}
```

### 资金池流水

```
GET /api/pool/ledger?fund_code=000083&limit=50
```

### 周度复盘

```
GET /api/reports/weekly?fund_code=000083&days=7
GET /api/reports/weekly?days=7          # 全组合
```

## Hermes 调用约束

### 1. 写操作前必须确认

```python
# ✅ 正确做法
print("=== 交易确认 ===")
print(f"基金: {fund_code}")
print(f"金额: ¥{amount}")
print(f"类型: {tx_type}")
print(f"从资金池: {from_pool}")
# 用户确认后:
r = requests.post(f"{API}/api/transactions", json={
    ..., "confirmed": True
})
```

### 2. 只读操作可以随意调用

```python
# ✅ get 类 API 不需要确认
r = requests.get(f"{API}/api/plan/latest?fund_code=000083")
```

### 3. 幂等保护

- 每日采样幂等键: `daily_sample:{code}:{date}`
- 交易幂等键: `tx:{code}:{date}:{type}:{amount}:{hash}`
- 资金池幂等键: `pool:{code}:{date}:{type}:{amount}:{hash}`

重复调用不创建重复记录。

### 4. 禁止

- ✗ 直接 `sqlite3.connect('data/trend.db')` 写数据
- ✗ 绕过 API 直接调 `sample_and_store_one`
- ✗ 伪造 `confirmed=True` 跳过用户确认
- ✗ 静默写入（必须输出确认摘要）

## 示例：Hermes 每日任务

```python
import requests
API = "http://127.0.0.1:8701"

# 1. 采样
r = requests.post(f"{API}/api/snapshot/daily/run", json={"created_by": "hermes"})
print(f"采样完成: {r.json()['count']} 个基金")

# 2. 查看计划
r = requests.get(f"{API}/api/plan/latest?fund_code=000083")
plan = r.json()
print(f"建议金额: ¥{plan['total_amount']:.2f}")
print(f"估值层级: {plan['level']}")

# 3. 周复盘
r = requests.get(f"{API}/api/reports/weekly?days=7")
print(r.json()["narrative"])
```
