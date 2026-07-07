# CompoundInterestPlan v2.0-RC Release Notes

## Overview

复利定投系统 MVP 稳定候选版。核心功能：策略信号 + Top10 持仓穿透 + 估值代理 + 暴露闸门 + 用户操作闭环 + 数据质量工作台。

## Key Features (v0.9 → v2.0)

### 策略与信号
- 核心-卫星价值定投框架
- 5只主动基金 + 1只纯债基金
- 固定定投 + 动态 DCA 双模式
- MA200 阈值：-10%/+5%

### 持仓穿透 (v1.0–v1.1)
- AKShare 真实持仓数据源接入
- Top10 重仓股 Jaccard 重叠计算
- 行业分布余弦相似度
- Local heuristics → fallback, never fake live data
- 状态：TOP10_ONLY_READY（非完整持仓穿透）

### 估值代理 (v1.5)
- 基金 → 代理指数映射（中证消费/医药/金融/沪深300/中债）
- PE/PB/股息率分位
- WEAK_PROXY → INFO_ONLY，不触发强制动作
- bond_pending → 不使用 PE/PB

### 暴露闸门 (v0.8–v1.2)
- 同主题最多 1 只可操作
- 行业暴露 >30% 停止动态 DCA
- Top10 重叠 >50% → observe
- Top10-only 不强制调低金额

### 用户操作闭环 (v1.3–v1.4)
- 6 种动作：BUY/OBSERVE/WATCH/REVIEW_REQUIRED/BLOCKED/NO_ACTION
- 金额展示策略：SHOW/SHOW_ZERO/AUDIT_ONLY/HIDE
- 资金池守卫：非 BUY 不得 executed
- 用户操作记录：executed/skipped/observed/reviewed/acknowledged

### 数据质量工作台 (v1.9)
- 扫描：NO_SNAPSHOT/WEAK_PROXY/STALE/INDUSTRY_MISSING
- 安全修复：仅数据源，不动金额/风控/交易
- 审计日志全程可追溯

### 审计与监控 (v1.4–v1.7)
- Full Exposure Audit：6 基金 × 15 对重叠矩阵
- Dashboard：系统状态 + 待办中心
- Weekly Review：周报聚合
- Handoff 报告自动生成

## Safety Guarantees

| 检查项 | 状态 |
|--------|------|
| 不自动交易 | ✅ |
| 不自动确认交易 | ✅ |
| AI 不决定金额 | ✅ |
| 估值层不改金额 | ✅ |
| Top10-only 不强制调低金额 | ✅ |
| 写入操作需用户确认 | ✅ |
| 数据质量只写 audit/issue 表 | ✅ |

## Known Limitations

- 持仓穿透：仅 Top10，中尾部重叠无法计算
- 估值数据：依赖 AKShare，沙箱/离线环境返回 SOURCE_ERROR
- 行业数据：AKShare 不提供基金行业分布
- 债券估值：未接入久期/信用评级指标

## Upgrade Path

- v2.1: 半年报 PDF 解析 → Top50+ 持仓
- v2.2: 行业数据补全
- v2.3: 债基久期/信用环境
