#!/usr/bin/env python3
"""
FastAPI 服务器 — v2.1 安全收口

- X-Local-Token 认证（写操作）
- CORS 只允许 localhost:8501
- DEBUG 模式控制 /docs
- 备份端点
"""

import sys
import os
import shutil
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional

from ..services.api_service import (
    api_daily_sample, api_get_latest, api_get_plan,
    api_create_transaction, api_delete_transaction,
    api_pool_deposit, api_pool_adjust, api_pool_ledger,
    api_weekly_report, init_transactions_table,
)
from ..core.config import load_all_funds_config

# ── 配置 ────────────────────────────────────────────

API_TOKEN = os.getenv("CIP_API_TOKEN", "local-dev-token-change-me")
DEBUG = os.getenv("CIP_DEBUG", "false").lower() in ("1", "true", "yes")
DB_PATH = Path("data/trend.db")
ALLOWED_ORIGINS = [
    "http://localhost:8501",
    "http://127.0.0.1:8501",
    "http://localhost:3000",
]

app = FastAPI(
    title="CompoundInterestPlan API",
    version="2.1",
    docs_url="/docs" if DEBUG else None,
    redoc_url=None,
)

# ── CORS ─────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-Local-Token", "Content-Type"],
)


@app.on_event("startup")
def startup():
    init_transactions_table()


# ── Auth ─────────────────────────────────────────────

def verify_token(request: Request):
    """写操作需要 X-Local-Token"""
    if request.method in ("GET",):
        return  # 读操作不校验
    token = request.headers.get("X-Local-Token", "")
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Local-Token")


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


# ── 写操作 Endpoints (需 token) ─────────────────────

@app.post("/api/snapshot/daily/run", dependencies=[Depends(verify_token)])
def post_daily_sample(req: DailySampleRequest):
    funds, _ = load_all_funds_config()
    results = []
    for cfg in funds:
        r = api_daily_sample(cfg, created_by=req.created_by, force=req.force)
        results.append(r)
    return {"count": len(results), "results": results}


@app.post("/api/transactions", dependencies=[Depends(verify_token)])
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


@app.delete("/api/transactions/{tx_id}", dependencies=[Depends(verify_token)])
def delete_transaction(tx_id: int):
    r = api_delete_transaction(tx_id)
    if r["status"] == "not_found":
        raise HTTPException(status_code=404, detail=r)
    return r


@app.post("/api/pool/deposit", dependencies=[Depends(verify_token)])
def pool_deposit(req: PoolDepositRequest):
    return api_pool_deposit(
        fund_code=req.fund_code, amount=req.amount,
        date_str=req.date or "", note=req.note, created_by=req.created_by,
    )


@app.post("/api/pool/adjust", dependencies=[Depends(verify_token)])
def pool_adjust(req: PoolAdjustRequest):
    return api_pool_adjust(
        fund_code=req.fund_code, amount=req.amount,
        note=req.note, created_by=req.created_by,
    )


# ── 读操作 Endpoints (无需 token) ────────────────────

@app.get("/api/snapshot/latest")
def get_latest(fund_code: str = Query("000083")):
    return api_get_latest(fund_code)


@app.get("/api/plan/latest")
def get_plan(fund_code: str = Query("000083")):
    return api_get_plan(fund_code)


@app.get("/api/pool/ledger")
def pool_ledger(fund_code: str = Query("000083"), limit: int = Query(50)):
    return api_pool_ledger(fund_code, limit)


@app.get("/api/reports/weekly")
def weekly_report(fund_code: Optional[str] = Query(None), days: int = Query(7)):
    return api_weekly_report(fund_code, days)


# ── 管理端点 ─────────────────────────────────────────

@app.post("/api/admin/backup", dependencies=[Depends(verify_token)])
def admin_backup():
    """使用 sqlite3 backup API 安全备份数据库"""
    import sqlite3
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = Path(f"data/trend.db.backup_{ts}")
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(backup_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    size = backup_path.stat().st_size
    return {
        "status": "ok",
        "backup_path": str(backup_path),
        "size_bytes": size,
        "timestamp": ts,
    }


# ── 健康检查 ─────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.1", "debug": DEBUG}


# ── 入口 ────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8701)
    p.add_argument("--host", type=str, default="127.0.0.1")
    args = p.parse_args()
    init_transactions_table()
    print(f"API Token: {API_TOKEN[:4]}... (set CIP_API_TOKEN in .env)")
    print(f"DEBUG: {DEBUG}")
    uvicorn.run(app, host=args.host, port=args.port)
