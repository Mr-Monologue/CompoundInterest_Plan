# SmartInvest v2.0 — 智能定投系统

基于网格策略的自主定投系统，纯后端，适配 RK3588 / clawbot。

## 文件结构

```
main.py          ← 数据模型 + 数据库 + 调度器 + 全部 API
services.py      ← 行情获取 + 策略引擎 + 组合调度 + 持仓穿透
requirements.txt ← 依赖
start.sh         ← 启动脚本
README.md        ← 本文件
```

## 快速开始

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./start.sh   # 或: python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

API 文档：http://localhost:8000/docs

## 策略简述

| 网格区间 | 动作 |
|----------|------|
| ≥ +2 格 | 暂停定投，全额蓄力 |
| 0 ~ +2 | 线性收缩（100% → 0%） |
| -2 ~ 0 | 标准定投 |
| ≤ -2 格 | 几何加码（最大 5 倍） |

双重刹车：单标的仓位上限 20%、行业穿透限额 30%。

## RK3588 部署

```bash
scp -r . clawbot@<IP>:/opt/smartinvest/
# 创建 systemd 服务：
# [Service]
# ExecStart=/opt/smartinvest/start.sh
# Restart=always
sudo systemctl enable smartinvest && sudo systemctl start smartinvest
```
