# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

SmartInvest v2.0 — 基于网格策略的智能定投系统，纯 Python 后端（FastAPI + SQLite + APScheduler）。目标部署平台：RK3588 硬件 / clawbot。

### Running the app

```bash
source .venv/bin/activate
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

或使用项目根目录的启动脚本：`./start.sh`

App 端口 8000，API 文档在 `/docs`。

### Dependencies

```bash
pip install -r requirements.txt
```

核心依赖：fastapi, uvicorn, sqlmodel, pandas, akshare, yfinance, apscheduler。

### Key gotchas

- 后端代码在 `backend/` 目录下，`main.py` 的 import 路径是相对于 `backend/` 的，必须在该目录下运行。
- SQLite 数据库文件 `invest.db` 生成在运行目录（即 `backend/`）下。
- `market.py` 会强制清除代理环境变量以确保直连国内数据源，在需要代理的环境中需注意。
- APScheduler 以 `Asia/Shanghai` 时区运行，定时任务的 cron 表达式基于中国时间。
- `strategy_engine.py` 和 `marcket.py` 是遗留文件，当前未被 `main.py` 调用。
