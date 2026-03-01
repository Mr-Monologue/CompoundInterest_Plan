import os
import logging

os.environ["http_proxy"] = ""
os.environ["https_proxy"] = ""
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["NO_PROXY"] = "*"

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select
import uvicorn
from contextlib import asynccontextmanager
from pydantic import BaseModel
from datetime import datetime

from db.database import create_db_and_tables, get_session
from db.models import Asset, Transaction, FundHolding
from services.market import get_strategy_advice
from services.strategy import (
    run_strategy_analysis,
    generate_weekly_report_text,
    get_instant_analysis,
)
from services.portfolio import (
    run_portfolio_strategy,
    get_global_state,
    adjust_pool_balance,
)
from services.holdings import sync_fund_holdings, get_fund_industry_vector
from scheduler import SmartInvestScheduler
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("smartinvest")

scheduler = SmartInvestScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    logger.info("数据库初始化完成")
    scheduler.start()
    logger.info("调度器已启动")
    yield
    scheduler.shutdown()
    logger.info("调度器已停止")


app = FastAPI(
    title="SmartInvest API",
    description="智能定投系统 — 纯后端服务，适配 RK3588 / clawbot 部署",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === 数据模型定义 ===
class AssetCreate(BaseModel):
    code: str
    name: str
    max_weight_limit: float = 0.2  # 默认20%


class TransactionCreate(BaseModel):
    asset_code: str
    type: str  # "BUY" 或 "SELL"
    price: float
    amount: float
    fee: float = 0.0  # 手续费（可选，如果为0则自动计算）
    date: str = None
    from_pool: bool = True  # 🔥 新增：是否从资金池扣款 (默认是)


# =======================
#        API 接口区
# =======================


# 2. 资产管理 (列表/添加)
@app.get("/api/assets")
def read_assets(session: Session = Depends(get_session)):
    return session.exec(select(Asset)).all()


@app.post("/api/assets")
def create_asset(asset: AssetCreate, session: Session = Depends(get_session)):
    existing = session.exec(select(Asset).where(Asset.code == asset.code)).first()
    if existing:
        return existing
    db_asset = Asset(
        code=asset.code,
        name=asset.name,
        max_weight_limit=asset.max_weight_limit,  # 写入数据库
    )
    session.add(db_asset)
    session.commit()
    session.refresh(db_asset)
    return db_asset


# === 新增：删除资产 ===
@app.delete("/api/assets/{asset_id}")
def delete_asset(asset_id: int, session: Session = Depends(get_session)):
    asset = session.get(Asset, asset_id)
    if not asset:
        return {"error": "Asset not found"}

    # 删除资产记录
    session.delete(asset)

    # 选做：如果你希望删除资产时，顺便把它的"存钱罐状态"也清空，可以加上下面这两行：
    # state = session.exec(select(FundState).where(FundState.asset_code == asset.code)).first()
    # if state: session.delete(state)

    session.commit()
    return {"ok": True}


# 3. 行情与建议 (实时)
@app.get("/api/advice/{code}")
def get_advice(code: str, session: Session = Depends(get_session)):
    # 1. 调策略模块的新接口，获取带建议的数据
    data = get_instant_analysis(code, session)

    # 2. 🔥 新增：查询该基金的前十大重仓股 🔥
    holdings = session.exec(
        select(FundHolding)
        .where(FundHolding.fund_code == code)
        .order_by(FundHolding.weight.desc())
        .limit(10)
    ).all()

    # 拼装到返回结果里
    data["top_holdings"] = [
        {"name": h.stock_name, "code": h.stock_code, "weight": h.weight}
        for h in holdings
    ]

    return data


# 4. 交易记录
@app.post("/api/transactions")
def create_transaction(tx: TransactionCreate, session: Session = Depends(get_session)):
    # 逻辑：前端如果没有传 fee，我们帮他自动算

    calc_fee = tx.fee
    # 如果前端传的 fee 是 0，且这不是卖出操作（卖出费率复杂，暂时忽略或由用户手填），我们估算买入费
    if calc_fee == 0 and tx.type == "BUY":
        rate = 0.0015 if tx.asset_code.isdigit() else 0.0002
        # 应用官方公式
        net_amt = tx.amount / (1 + rate)
        calc_fee = tx.amount - net_amt

    net_amount = tx.amount - calc_fee

    # 份额 = 净金额 / 单价
    units = net_amount / tx.price

    # 1. 记录交易
    db_tx = Transaction(
        asset_code=tx.asset_code,
        type=tx.type,
        price=tx.price,
        amount=tx.amount,
        fee=calc_fee,
        units=units,
        date=datetime.now() if not tx.date else datetime.strptime(tx.date, "%Y-%m-%d"),
    )
    session.add(db_tx)

    # 2. 🔥 如果勾选了从池子扣，扣减 Pool 🔥
    if tx.type == "BUY" and tx.from_pool:
        state = get_global_state(session)
        if state.pool_balance >= tx.amount:
            state.pool_balance -= tx.amount
            session.add(state)
        else:
            # 也可以选择报错，或者扣成负数，这里简单扣成负数也没事，代表透支
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
                ratio = tx.units / (total_units + tx.units)
                total_cost = total_cost * (1 - ratio)
    return {
        "asset_code": code,
        "total_units": round(total_units, 2),
        "total_cost": round(total_cost, 2),
        "history_count": len(txs),
    }


# === 新增：获取交易历史 ===
@app.get("/api/transactions/{code}")
def get_transactions(code: str, session: Session = Depends(get_session)):
    """获取某个资产的所有交易记录"""
    txs = session.exec(
        select(Transaction)
        .where(Transaction.asset_code == code)
        .order_by(Transaction.date.desc())
    ).all()
    return txs


# === 新增：修改交易 ===
@app.put("/api/transactions/{tx_id}")
def update_transaction(
    tx_id: int, new_data: TransactionCreate, session: Session = Depends(get_session)
):
    """修改交易 (更新金额/价格/日期)"""
    tx = session.get(Transaction, tx_id)
    if not tx:
        return {"error": "未找到记录"}

    # 💡 这是一个复杂问题：修改交易是否要回滚资金池？
    # 为了简化逻辑，建议：修改只改记录本身，不动资金池。
    # 如果要动资金池，建议用户"删除重记"。

    # 更新字段
    tx.price = new_data.price
    tx.amount = new_data.amount
    # 重新计算份额
    net_amt = tx.amount - tx.fee  # 简便起见假设 fee 不变或由前端传
    tx.units = net_amt / tx.price

    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx


# === 新增：删除交易 ===
@app.delete("/api/transactions/{tx_id}")
def delete_transaction(tx_id: int, session: Session = Depends(get_session)):
    """删除交易"""
    tx = session.get(Transaction, tx_id)
    if not tx:
        return {"error": "未找到"}

    # 🔥 删除时，是否把钱退回资金池？
    # 这是一个设计选择。通常建议：如果当时是从池子扣的，删除时应该退回去。
    # 但因为 Transaction 表没记"是否来自池子"，这里简单处理：不退。
    # 用户可以在资金池手动"充值"来平账。

    session.delete(tx)
    session.commit()
    return {"ok": True}


# === 🔥 5. 策略复盘 (新功能) 🔥 ===


# 执行策略分析 (采样)
# 改为路径参数，Swagger 里直接填代码即可
@app.post("/api/strategy/run/{code}")
def run_strategy(code: str, session: Session = Depends(get_session)):
    try:
        result = run_strategy_analysis(code, session)
        return result
    except Exception as e:
        return {"error": str(e)}


# 获取复盘报告
@app.get("/api/strategy/report/{code}")
def get_report(code: str, days: int = 7, session: Session = Depends(get_session)):
    report = generate_weekly_report_text(code, session, days)
    return {"report": report}


# === 🔥 6. 全局投资计划 (新功能) 🔥 ===


# === API: 获取 Pool 状态 ===
@app.get("/api/pool")
def get_pool_info(session: Session = Depends(get_session)):
    state = get_global_state(session)
    return {
        "pool_balance": state.pool_balance,
        "base_investment": state.base_investment,
        "deposit_frequency": state.deposit_frequency,
    }


# === API: 资金池充值 (Top-up) ===
@app.post("/api/pool/deposit")
def deposit_pool(data: dict, session: Session = Depends(get_session)):
    # data: {"amount": 1000}
    amount = float(data.get("amount", 0))
    if amount <= 0:
        return {"error": "金额必须大于0"}

    state = adjust_pool_balance(session, amount, "DEPOSIT")
    return {"ok": True, "new_balance": state.pool_balance}


# === API: 更新配置 (修改定投基准 或 直接修正资金池余额) ===
@app.post("/api/pool/config")
def update_pool_config(data: dict, session: Session = Depends(get_session)):
    # data: {"base_investment": 300, "pool_balance": 500}
    state = get_global_state(session)

    # 1. 修改基准
    if "base_investment" in data:
        state.base_investment = float(data["base_investment"])

    # 2. 🔥 新增：直接修正资金池余额 🔥
    if "pool_balance" in data:
        # 允许用户直接指定一个数字，比如 200
        state.pool_balance = float(data["pool_balance"])

    session.add(state)
    session.commit()
    return {
        "ok": True,
        "base_investment": state.base_investment,
        "pool_balance": state.pool_balance,
    }


# === API: 获取全局状态 (看板用) - 保留兼容性 ===
@app.get("/api/plan/state")
def get_plan_state(session: Session = Depends(get_session)):
    state = get_global_state(session)
    return {
        "pool_balance": state.pool_balance,
        "base_investment": state.base_investment,
        "deposit_frequency": state.deposit_frequency,
    }


# === API: 一键执行全组合策略 ===
@app.post("/api/plan/run")
def run_all_strategies(session: Session = Depends(get_session)):
    try:
        result = run_portfolio_strategy(session)
        return result
    except Exception as e:
        import traceback

        traceback.print_exc()
        return {"error": str(e)}


# === API: 强制同步某基金的持仓 ===
@app.post("/api/holdings/sync/{code}")
def sync_holdings(code: str, session: Session = Depends(get_session)):
    try:
        sync_fund_holdings(session, code)
        return {"ok": True}
    except Exception as e:
        import traceback

        traceback.print_exc()
        return {"error": str(e)}


# === API: 获取全组合的穿透式行业分布 ===
@app.get("/api/analysis/industry")
def get_industry_analysis(session: Session = Depends(get_session)):
    assets = session.exec(select(Asset)).all()

    # 1. 统计各行业总市值
    industry_market_value = defaultdict(float)
    total_portfolio_value = 0.0

    for asset in assets:
        # 获取当前持仓市值
        txs = session.exec(
            select(Transaction).where(Transaction.asset_code == asset.code)
        ).all()
        units = sum(t.units for t in txs if t.type == "BUY") - sum(
            t.units for t in txs if t.type == "SELL"
        )

        if units <= 0:
            continue

        # 获取现价
        mdata = get_strategy_advice(asset.code, asset.name)
        if mdata.get("action") == "ERROR":
            continue

        current_mv = units * mdata["current_price"]
        total_portfolio_value += current_mv

        # 获取该基金的行业向量
        ind_vector = get_fund_industry_vector(session, asset.code)

        if ind_vector:
            for ind, weight in ind_vector.items():
                industry_market_value[ind] += current_mv * weight
        else:
            # 如果没穿透数据（比如新基金没抓取），暂时归为"其他"
            industry_market_value["未穿透/其他"] += current_mv

    if total_portfolio_value == 0:
        return []

    # 2. 格式化输出 (按占比降序)
    result = []
    for ind, mv in industry_market_value.items():
        ratio = mv / total_portfolio_value
        result.append(
            {"name": ind, "value": round(mv, 2), "ratio": round(ratio * 100, 2)}
        )

    # 按占比排序
    result.sort(key=lambda x: x["ratio"], reverse=True)
    return result


# =======================
#    运维与调度 API
# =======================


@app.get("/api/health")
def health_check():
    """健康检查端点，用于 clawbot / 监控系统探活"""
    return {
        "status": "ok",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "scheduler_running": scheduler.is_running(),
    }


@app.get("/api/system/status")
def system_status(session: Session = Depends(get_session)):
    """系统状态总览"""
    assets = session.exec(select(Asset)).all()
    state = get_global_state(session)
    jobs = scheduler.list_jobs()
    return {
        "assets_count": len(assets),
        "pool_balance": state.pool_balance,
        "base_investment": state.base_investment,
        "deposit_frequency": state.deposit_frequency,
        "scheduler": {
            "running": scheduler.is_running(),
            "jobs": jobs,
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/scheduler/jobs")
def get_scheduler_jobs():
    """查看所有定时任务"""
    return {"jobs": scheduler.list_jobs()}


@app.post("/api/scheduler/trigger/{job_id}")
def trigger_job(job_id: str):
    """手动触发指定任务"""
    ok = scheduler.trigger_job(job_id)
    if ok:
        return {"ok": True, "message": f"任务 {job_id} 已触发"}
    return {"ok": False, "message": f"任务 {job_id} 不存在"}


@app.post("/api/scheduler/pause/{job_id}")
def pause_job(job_id: str):
    """暂停指定任务"""
    ok = scheduler.pause_job(job_id)
    return {"ok": ok}


@app.post("/api/scheduler/resume/{job_id}")
def resume_job(job_id: str):
    """恢复指定任务"""
    ok = scheduler.resume_job(job_id)
    return {"ok": ok}


# =======================
#    根路径
# =======================


@app.get("/")
def root():
    return {
        "service": "SmartInvest",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/api/health",
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
