"""
SmartInvest v2.0 — 智能定投系统
纯后端架构，适配 RK3588 / clawbot 部署

本文件包含：调度器 + FastAPI 应用 + 全部 API 路由
数据模型见 models.py，业务逻辑见 services.py
"""

import os
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from collections import defaultdict

os.environ.update({"http_proxy": "", "https_proxy": "", "HTTP_PROXY": "", "HTTPS_PROXY": "", "NO_PROXY": "*"})

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select
from pydantic import BaseModel
import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from models import (
    Asset, Transaction, FundHolding, PlanState,
    engine, create_db_and_tables, get_session, get_global_state,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("smartinvest")


# =============================================
#  调度器
# =============================================


class SmartInvestScheduler:
    def __init__(self):
        self._scheduler = BackgroundScheduler(timezone="Asia/Shanghai", job_defaults={"coalesce": True, "max_instances": 1})
        self._scheduler.add_job(self._job_daily_strategy, CronTrigger(day_of_week="mon-fri", hour=15, minute=30),
                                id="daily_strategy", name="每日策略执行", replace_existing=True)
        self._scheduler.add_job(self._job_auto_deposit, CronTrigger(day_of_week="mon", hour=9, minute=0),
                                id="weekly_deposit", name="每周自动充值", replace_existing=True)
        self._scheduler.add_job(self._job_sync_holdings, CronTrigger(day_of_week="sun", hour=2, minute=0),
                                id="sync_holdings", name="持仓数据同步", replace_existing=True)

    def start(self):
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self):
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def is_running(self) -> bool:
        return self._scheduler.running

    def list_jobs(self) -> list:
        return [{"id": j.id, "name": j.name,
                 "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
                 "paused": j.next_run_time is None} for j in self._scheduler.get_jobs()]

    def trigger_job(self, job_id: str) -> bool:
        job = self._scheduler.get_job(job_id)
        if job:
            job.modify(next_run_time=datetime.now())
            return True
        return False

    def pause_job(self, job_id: str) -> bool:
        try:
            self._scheduler.pause_job(job_id)
            return True
        except Exception:
            return False

    def resume_job(self, job_id: str) -> bool:
        try:
            self._scheduler.resume_job(job_id)
            return True
        except Exception:
            return False

    def _job_daily_strategy(self):
        from services import run_portfolio_strategy
        logger.info("=== [定时] 每日策略执行 ===")
        try:
            with Session(engine) as session:
                result = run_portfolio_strategy(session)
                for s in result.get("suggestions", []):
                    if s["amt"] > 0:
                        logger.info(f"  📈 {s['code']} {s['name']}: ¥{s['amt']:.0f} - {s['msg']}")
                    else:
                        logger.info(f"  ⏸️  {s['code']} {s['name']}: {s['msg']}")
        except Exception as e:
            logger.error(f"每日策略失败: {e}", exc_info=True)

    def _job_auto_deposit(self):
        from services import adjust_pool_balance
        logger.info("=== [定时] 自动充值检查 ===")
        try:
            with Session(engine) as session:
                state = get_global_state(session)
                if state.deposit_frequency == "MANUAL" or state.auto_deposit_amount <= 0:
                    logger.info("  跳过（手动模式或金额为0）")
                    return
                state = adjust_pool_balance(session, state.auto_deposit_amount, "DEPOSIT")
                logger.info(f"  ✅ 充值 ¥{state.auto_deposit_amount:.0f}，余额 ¥{state.pool_balance:.2f}")
        except Exception as e:
            logger.error(f"自动充值失败: {e}", exc_info=True)

    def _job_sync_holdings(self):
        from services import sync_fund_holdings
        logger.info("=== [定时] 持仓同步 ===")
        try:
            with Session(engine) as session:
                for asset in session.exec(select(Asset)).all():
                    try:
                        sync_fund_holdings(session, asset.code)
                    except Exception as e:
                        logger.warning(f"  {asset.code} 同步失败: {e}")
        except Exception as e:
            logger.error(f"持仓同步失败: {e}", exc_info=True)


scheduler = SmartInvestScheduler()


# =============================================
#  FastAPI 应用
# =============================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    logger.info("数据库初始化完成")
    scheduler.start()
    logger.info("调度器已启动")
    yield
    scheduler.shutdown()


app = FastAPI(title="SmartInvest API", version="2.0.0",
              description="智能定投系统 — 纯后端，适配 RK3588 / clawbot", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class AssetCreate(BaseModel):
    code: str
    name: str
    max_weight_limit: float = 0.2


class TransactionCreate(BaseModel):
    asset_code: str
    type: str
    price: float
    amount: float
    fee: float = 0.0
    date: str = None
    from_pool: bool = False


# --- 资产管理 ---

@app.get("/api/assets")
def read_assets(session: Session = Depends(get_session)):
    return session.exec(select(Asset)).all()


@app.post("/api/assets")
def create_asset(asset: AssetCreate, session: Session = Depends(get_session)):
    existing = session.exec(select(Asset).where(Asset.code == asset.code)).first()
    if existing:
        return existing
    db_asset = Asset(code=asset.code, name=asset.name, max_weight_limit=asset.max_weight_limit)
    session.add(db_asset)
    session.commit()
    session.refresh(db_asset)
    return db_asset


@app.delete("/api/assets/{asset_id}")
def delete_asset(asset_id: int, session: Session = Depends(get_session)):
    asset = session.get(Asset, asset_id)
    if not asset:
        return {"error": "Asset not found"}
    session.delete(asset)
    session.commit()
    return {"ok": True}


# --- 行情与策略 ---

@app.get("/api/advice/{code}")
def get_advice(code: str, session: Session = Depends(get_session)):
    from services import get_instant_analysis
    return get_instant_analysis(code, session)


@app.post("/api/strategy/run/{code}")
def run_strategy(code: str, session: Session = Depends(get_session)):
    from services import run_strategy_analysis
    try:
        return run_strategy_analysis(code, session)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/strategy/report/{code}")
def get_report(code: str, days: int = 7, session: Session = Depends(get_session)):
    from services import generate_weekly_report_text
    return {"report": generate_weekly_report_text(code, session, days)}


@app.post("/api/plan/run")
def run_all_strategies(session: Session = Depends(get_session)):
    from services import run_portfolio_strategy
    try:
        return run_portfolio_strategy(session)
    except Exception as e:
        return {"error": str(e)}


# --- 交易记录 ---

@app.post("/api/transactions")
def create_transaction(tx: TransactionCreate, session: Session = Depends(get_session)):
    calc_fee = tx.fee
    if calc_fee == 0 and tx.type == "BUY":
        rate = 0.0015 if tx.asset_code.isdigit() else 0.0002
        net_amt = tx.amount / (1 + rate)
        calc_fee = tx.amount - net_amt

    net_amount = tx.amount - calc_fee
    units = net_amount / tx.price

    db_tx = Transaction(
        asset_code=tx.asset_code, type=tx.type, price=tx.price,
        amount=tx.amount, fee=calc_fee, units=units,
        date=datetime.now() if not tx.date else datetime.strptime(tx.date, "%Y-%m-%d"),
    )
    session.add(db_tx)

    if tx.type == "BUY" and tx.from_pool:
        state = get_global_state(session)
        state.pool_balance -= tx.amount
        session.add(state)

    session.commit()
    session.refresh(db_tx)
    return db_tx


@app.get("/api/portfolio/{code}")
def get_portfolio_stats(code: str, session: Session = Depends(get_session)):
    txs = session.exec(select(Transaction).where(Transaction.asset_code == code)).all()
    total_units = 0.0
    total_cost = 0.0
    for tx in txs:
        if tx.type == "BUY":
            total_units += tx.units
            total_cost += tx.amount
        elif tx.type == "SELL":
            total_units -= tx.units
            if total_units > 0:
                total_cost *= 1 - tx.units / (total_units + tx.units)
    return {"asset_code": code, "total_units": round(total_units, 2),
            "total_cost": round(total_cost, 2), "history_count": len(txs)}


@app.get("/api/transactions/{code}")
def get_transactions(code: str, session: Session = Depends(get_session)):
    return session.exec(select(Transaction).where(Transaction.asset_code == code).order_by(Transaction.date.desc())).all()


@app.put("/api/transactions/{tx_id}")
def update_transaction(tx_id: int, new_data: TransactionCreate, session: Session = Depends(get_session)):
    tx = session.get(Transaction, tx_id)
    if not tx:
        return {"error": "未找到记录"}
    tx.price = new_data.price
    tx.amount = new_data.amount
    tx.units = (tx.amount - tx.fee) / tx.price
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx


@app.delete("/api/transactions/{tx_id}")
def delete_transaction(tx_id: int, session: Session = Depends(get_session)):
    tx = session.get(Transaction, tx_id)
    if not tx:
        return {"error": "未找到"}
    session.delete(tx)
    session.commit()
    return {"ok": True}


# --- 资金池 ---

@app.get("/api/pool")
def get_pool_info(session: Session = Depends(get_session)):
    state = get_global_state(session)
    return {"pool_balance": state.pool_balance, "base_investment": state.base_investment,
            "deposit_frequency": state.deposit_frequency}


@app.post("/api/pool/deposit")
def deposit_pool(data: dict, session: Session = Depends(get_session)):
    from services import adjust_pool_balance
    amount = float(data.get("amount", 0))
    if amount <= 0:
        return {"error": "金额必须大于0"}
    state = adjust_pool_balance(session, amount, "DEPOSIT")
    return {"ok": True, "new_balance": state.pool_balance}


@app.post("/api/pool/config")
def update_pool_config(data: dict, session: Session = Depends(get_session)):
    state = get_global_state(session)
    if "base_investment" in data:
        state.base_investment = float(data["base_investment"])
    if "pool_balance" in data:
        state.pool_balance = float(data["pool_balance"])
    session.add(state)
    session.commit()
    return {"ok": True, "base_investment": state.base_investment, "pool_balance": state.pool_balance}


@app.get("/api/plan/state")
def get_plan_state(session: Session = Depends(get_session)):
    state = get_global_state(session)
    return {"pool_balance": state.pool_balance, "base_investment": state.base_investment,
            "deposit_frequency": state.deposit_frequency}


# --- 持仓 & 行业分析 ---

@app.post("/api/holdings/sync/{code}")
def sync_holdings(code: str, session: Session = Depends(get_session)):
    from services import sync_fund_holdings
    try:
        sync_fund_holdings(session, code)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/analysis/industry")
def get_industry_analysis(session: Session = Depends(get_session)):
    from services import get_strategy_advice, get_fund_industry_vector
    assets = session.exec(select(Asset)).all()
    industry_mv = defaultdict(float)
    total_value = 0.0

    for asset in assets:
        txs = session.exec(select(Transaction).where(Transaction.asset_code == asset.code)).all()
        units = sum(t.units for t in txs if t.type == "BUY") - sum(t.units for t in txs if t.type == "SELL")
        if units <= 0:
            continue
        mdata = get_strategy_advice(asset.code, asset.name)
        if mdata.get("action") == "ERROR":
            continue
        current_mv = units * mdata["current_price"]
        total_value += current_mv
        ind_vector = get_fund_industry_vector(session, asset.code)
        if ind_vector:
            for ind, weight in ind_vector.items():
                industry_mv[ind] += current_mv * weight
        else:
            industry_mv["未穿透/其他"] += current_mv

    if total_value == 0:
        return []
    result = [{"name": ind, "value": round(mv, 2), "ratio": round(mv / total_value * 100, 2)}
              for ind, mv in industry_mv.items()]
    result.sort(key=lambda x: x["ratio"], reverse=True)
    return result


# --- 运维与调度 ---

@app.get("/")
def root():
    return {"service": "SmartInvest", "version": "2.0.0", "docs": "/docs", "health": "/api/health"}


@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": "2.0.0", "timestamp": datetime.now().isoformat(),
            "scheduler_running": scheduler.is_running()}


@app.get("/api/system/status")
def system_status(session: Session = Depends(get_session)):
    state = get_global_state(session)
    return {"assets_count": len(session.exec(select(Asset)).all()), "pool_balance": state.pool_balance,
            "base_investment": state.base_investment, "deposit_frequency": state.deposit_frequency,
            "scheduler": {"running": scheduler.is_running(), "jobs": scheduler.list_jobs()},
            "timestamp": datetime.now().isoformat()}


@app.get("/api/scheduler/jobs")
def get_scheduler_jobs():
    return {"jobs": scheduler.list_jobs()}


@app.post("/api/scheduler/trigger/{job_id}")
def trigger_job(job_id: str):
    return {"ok": scheduler.trigger_job(job_id)}


@app.post("/api/scheduler/pause/{job_id}")
def pause_job(job_id: str):
    return {"ok": scheduler.pause_job(job_id)}


@app.post("/api/scheduler/resume/{job_id}")
def resume_job(job_id: str):
    return {"ok": scheduler.resume_job(job_id)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
