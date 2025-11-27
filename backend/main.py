import os

# 强制禁用代理，确保 Python 能走 VPN 或直连
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

# 引入各个模块
from db.database import create_db_and_tables, get_session
from db.models import Asset, Transaction
from services.market import get_strategy_advice
from services.strategy import (
    run_strategy_analysis,
    generate_weekly_report_text,
    get_instant_analysis,
)
from services.portfolio import run_portfolio_strategy
from db.state import get_global_state


# === 生命周期：启动时建表 ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    print("✅ 数据库初始化完成！")
    yield


app = FastAPI(lifespan=lifespan)

# === 跨域配置 ===
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


class TransactionCreate(BaseModel):
    asset_code: str
    type: str  # "BUY" 或 "SELL"
    price: float
    amount: float
    fee: float = 0.0  # 手续费（可选，如果为0则自动计算）
    date: str = None


# =======================
#        API 接口区
# =======================


# 1. 基础测试
@app.get("/")
def read_root():
    return {"message": "智能定投系统后端 v2.0 在线"}


# 2. 资产管理 (列表/添加)
@app.get("/api/assets")
def read_assets(session: Session = Depends(get_session)):
    return session.exec(select(Asset)).all()


@app.post("/api/assets")
def create_asset(asset: AssetCreate, session: Session = Depends(get_session)):
    existing = session.exec(select(Asset).where(Asset.code == asset.code)).first()
    if existing:
        return existing
    db_asset = Asset(code=asset.code, name=asset.name)
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
    return get_instant_analysis(code, session)


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


# === API: 获取全局状态 (看板用) ===
@app.get("/api/plan/state")
def get_plan_state(session: Session = Depends(get_session)):
    state = get_global_state(session)
    # 计算本周剩余
    left = state.weekly_budget - state.budget_used_this_week
    return {
        "weekly_budget": state.weekly_budget,
        "budget_left": max(0, left),
        "global_reserve": state.global_reserve,
        "week_start": state.current_week_start,
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


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
