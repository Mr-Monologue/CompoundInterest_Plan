# 迁移说明 — hermes/refactor-risk-guard

> 从 master 到 hermes/refactor-risk-guard 分支的变更说明。
> 日期：2026-06-16

---

## 变更概述

将 CompoundInterestPlan 从「个人实验项目」升级为「**可审计、可测试、可用于实盘辅助**」的版本。
系统只给投资建议，不自动下单。

---

## 新文件

| 文件 | 作用 |
|------|------|
| `src/app/core/models.py` | 统一数据模型（Asset, Transaction, DailyPlan, PoolLedger 等） |
| `src/app/core/strategy.py` | 唯一生产策略 — MA200 偏离度动态定投 |
| `src/app/core/risk_guard.py` | 风险防护 — Mock 数据拦截、异常值阻断 |
| `src/app/services/accounting.py` | Decimal 会计核算 — 支付宝口径 |
| `src/app/services/pool_ledger.py` | 资金池流水账 — 禁止透支、删除回滚 |
| `tests/test_phase1.py` | 15 个核心测试（100% 通过） |
| `data/trend.db.bak_YYYYMMDD_HHMMSS` | 数据库备份 |

## 修改文件

| 文件 | 变更 |
|------|------|
| `src/app/services/actions.py` | **关键 BUG 修复**：dev_pct 从 (fund_nav-ma200)/ma200 修正为 (proxy_close-ma200)/ma200；集成 risk_guard 和 accounting |
| `src/app/ui/gui.py` | 新增数据源展示、risk_guard 状态展示、风险阻断提示 |

## 数据库变更

| 变更 | 说明 |
|------|------|
| 新增表 `pool_ledger` | 资金池流水账（CREATE TABLE IF NOT EXISTS，不删任何数据） |
| 备份文件 | `data/trend.db.bak_20260616_141746` |

**原有的 9 张表（nav_daily, proxy_daily, dca_plan, holdings_snapshot, nav_daily_v2, proxy_daily_v2, dca_plan_v2, holdings_snapshot_v2, fund_state）和数据完整无损。**

---

## 关键 BUG 修复

**修复前**（`actions.py` 第 45 行）：
```python
dev = calculate_ma200_deviation(df_idx, nav)  # 传入基金净值！
```
→ dev_pct = `(基金净值 - 代理MA200) / 代理MA200`，如 `(5.128 - 15100.25) / 15100.25 = -99.97%`（完全错误）

**修复后**：
```python
dev_pct = calculate_ma200_deviation(proxy_close, proxy_ma200)  # 传入代理指数价格
```
→ dev_pct = `(代理指数收盘价 - 代理MA200) / 代理MA200`，如 `(15150 - 15100.25) / 15100.25 = 0.33%`（正确）

**影响**：数据库中现有的 -99.97% 偏离度数据是因为此 BUG 写入的，下次采样将自动写入正确值。

---

## 如何在新设备上部署

```bash
# 1. 克隆（或切换分支）
git checkout hermes/refactor-risk-guard

# 2. 创建虚拟环境
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 如有旧数据库，先备份
cp data/trend.db data/trend.db.bak_$(date +%Y%m%d)

# 5. 初始化 pool_ledger 表（自动安全）
python -c "from src.app.services.pool_ledger import init_pool_ledger_db; init_pool_ledger_db()"

# 6. 运行测试
python -m pytest tests/ -v -o 'addopts='

# 7. 启动 GUI
python run_gui.py
```

---

## 风险防护规则

下列任一条件触发时，系统**禁止生成投资建议**，前端只显示"数据异常，需要人工复核"：

1. 数据源为 "Mock" 或 "mock"
2. 基金净值 ≤ 0 或 > 20
3. MA200 ≤ 0
4. |MA200 偏离度| > 50%
5. 准备金余额 < 0
6. 单周定投金额超过上限（周预算 × 3）

失败时静默降级被**明确禁止**，必须返回可见的错误信息。

---

## 测试清单（15/15 PASS）

| # | 测试 | 验证内容 |
|---|------|----------|
| 1 | `test_decimal_matches_alipay_display` | 支付宝口径持仓计算（4 个断言全部匹配） |
| 2 | `test_mock_source_blocks_advice` | Mock 源阻断 |
| 3 | `test_valid_source_passes` | AKShare 源通过 |
| 4 | `test_ma200_dev_uses_proxy_index` | 偏离度来源是代理指数 |
| 5 | `test_ma200_zero_rejected` | MA200 非法值拒绝 |
| 6 | `test_high_dynamic_zero` | 高估动态=0 |
| 7 | `test_low_uses_reserve` | 低估动用准备金 75% |
| 8 | `test_mid_interpolation` | 中估线性插值 |
| 9 | `test_weekly_cap_enforced` | 单周上限约束 |
| 10 | `test_no_pool_overdraft` | 资金池禁止透支 |
| 11 | `test_delete_pool_buy_refunds_pool` | 删除 BUY 退款 |
| 12 | `test_dailyplan_dev_pct_not_grid_pos` | dev_pct ≠ grid_pos |
| 13 | `test_risk_guard_nav_abnormal` | NAV 异常检测 |
| 14 | `test_risk_guard_dev_pct_abnormal` | 偏离度异常检测 |
| 15 | `test_risk_guard_format_rejection` | 拒绝消息格式 |
