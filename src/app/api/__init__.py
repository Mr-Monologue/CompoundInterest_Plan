#!/usr/bin/env python3
"""
FastAPI 服务器 — 对外暴露 REST API，供 Hermes / 外部系统调用。

启动: python -m src.app.api.server --port 8701
"""

import sys
from pathlib import Path

# 确保项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import date as DateType

from ..services.api_service import (
    api_daily_sample, api_get_latest, api_get_plan,
    api_create_transaction, api_delete_transaction,
    api_pool_deposit, api_pool_adjust, api_pool_ledger,
    api_weekly_report, init_transactions_table,
)
from ..core.config import load_all_funds_config

app = FastAPI(title="CompoundInterestPlan API", version="2.0")


@app.on_event("startup")
def startup():
    init_transactions_table()


# ── Models ──────────────────────────────────────────

class DailySampleRequest(BaseModel):
    created_by: str = "hermes"
    force: bool = False


class TransactionRequest(BaseModel):
    fund_code: str
    date: str
    tx_type: str = "BUY"
    amount: float
    units: float = 0.0
    nav: float = 0.0
    from_pool: bool = False
    note: str = ""
    created_by: str = "hermes"
    external_ref: str = ""
    confirmed: bool = False


class PoolDepositRequest(BaseModel):
    fund_code: str
    amount: float
    date: Optional[str] = None
    note: str = ""
    created_by: str = "hermes"


class PoolAdjustRequest(BaseModel):
    fund_code: str
    amount: float
    note: str
    created_by: str = "manual"


# ── Endpoints ───────────────────────────────────────

@app.post("/api/snapshot/daily/run")
def post_daily_sample(req: DailySampleRequest):
    """每日采样 — 对配置中所有基金执行"""
    funds, _ = load_all_funds_config()
    results = []
    for cfg in funds:
        r = api_daily_sample(cfg, created_by=req.created_by, force=req.force)
        results.append(r)
    return {"count": len(results), "results": results}


@app.get("/api/snapshot/latest")
def get_latest(fund_code: str = Query("000083")):
    return api_get_latest(fund_code)


@app.get("/api/plan/latest")
def get_plan(fund_code: str = Query("000083")):
    return api_get_plan(fund_code)


@app.post("/api/transactions")
def create_transaction(req: TransactionRequest):
    r = api_create_transaction(
        fund_code=req.fund_code, date_str=req.date, tx_type=req.tx_type,
        amount=req.amount, units=req.units, nav=req.nav,
        from_pool=req.from_pool, note=req.note,
        created_by=req.created_by, external_ref=req.external_ref,
        confirmed=req.confirmed,
    )
    if r.get("status") == "confirmation_required":
        raise HTTPException(status_code=409, detail=r)
    if r.get("status") == "rejected":
        raise HTTPException(status_code=400, detail=r)
    return r


@app.delete("/api/transactions/{tx_id}")
def delete_transaction(tx_id: int):
    r = api_delete_transaction(tx_id)
    if r["status"] == "not_found":
        raise HTTPException(status_code=404, detail=r)
    return r


@app.post("/api/pool/deposit")
def pool_deposit(req: PoolDepositRequest):
    return api_pool_deposit(
        fund_code=req.fund_code, amount=req.amount,
        date_str=req.date or "", note=req.note, created_by=req.created_by,
    )


@app.post("/api/pool/adjust")
def pool_adjust(req: PoolAdjustRequest):
    return api_pool_adjust(
        fund_code=req.fund_code, amount=req.amount,
        note=req.note, created_by=req.created_by,
    )


@app.get("/api/pool/ledger")
def pool_ledger(fund_code: str = Query("000083"), limit: int = Query(50)):
    return api_pool_ledger(fund_code, limit)


@app.get("/api/reports/weekly")
def weekly_report(fund_code: Optional[str] = Query(None), days: int = Query(7)):
    return api_weekly_report(fund_code, days)


# ── 入口 ────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8701)
    p.add_argument("--host", type=str, default="127.0.0.1")
    args = p.parse_args()
    init_transactions_table()
    uvicorn.run(app, host=args.host, port=args.port)
