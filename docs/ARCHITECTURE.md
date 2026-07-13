# Architecture

## 分层

```
frontend/     React + Vite (731)
backend/      FastAPI (9600)
  api/        路由 (weekly_plan, exposure)
  application/ 应用层 (weekly_plan orchestration)
  services/   领域服务 (valuation, strategy, portfolio, …)
  db/         模型 + 迁移 + 数据库
compoundctl.py 全栈控制 (start/stop/gate/doctor)
hermes/        Hermes Operator 集成
ops/           部署脚本 (Windows/Linux)
```

## 数据流
1. 每日采样 → DailyDecision (策略信号 + 持仓重叠 + 估值)
2. 周计划冻结 → WeeklyInvestmentPlan + WeeklyPlanItem + DecisionJournalEntry
3. 月复盘 → 用户决策回顾 + 规则迭代

## 安全边界
- GET API: 只读
- POST scan/fix: 仅写 DataQualityIssue/AuditLog
- 金额修改: 仅通过人工确认后写 Transaction
- Agent: 永不自动交易

## 部署
- compoundctl.py 控制全部生命周期
- ops/ 提供 Windows/Linux systemd 部署
- Hermes operator 提供自动健康检查 + 恢复
