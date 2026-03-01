# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

SmartInvest v2.0 — 网格策略智能定投系统。仅 2 个 Python 文件：`main.py`（API + 模型 + 调度器）和 `services.py`（业务逻辑）。

### Running

```bash
source .venv/bin/activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Key gotchas

- `services.py` 通过延迟导入 `from main import Model` 来引用数据模型，避免循环依赖。
- SQLite 数据库 `invest.db` 在项目根目录生成，可通过环境变量 `SMARTINVEST_DB` 修改路径。
- `market.py` 逻辑会清除代理环境变量以直连国内数据源。
- APScheduler 使用 `Asia/Shanghai` 时区。
