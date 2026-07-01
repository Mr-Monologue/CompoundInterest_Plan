import os

# 强制禁用代理，确保 Python 能走 VPN 或直连
os.environ["http_proxy"] = ""
os.environ["https_proxy"] = ""
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["NO_PROXY"] = "*"

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlmodel import Session, select
import uvicorn
from contextlib import asynccontextmanager
from pydantic import BaseModel
from datetime import datetime

# 引入各个模块
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
from collections import defaultdict


# === 生命周期：启动时建表 ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    print("✅ 数据库初始化完成！")
    yield


app = FastAPI(lifespan=lifespan)

# v1.0.1: AI Exposure Analyst router
from api.exposure import router as exposure_router
app.include_router(exposure_router)

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
    try:
        from services.market import risk_guard
        data = get_instant_analysis(code, session)
    except Exception:
        return {"ok": False, "reason": "legacy endpoint", "next_action": "use /api/decision/today"}

    # Add risk_guard + action_allowed
    if data.get("action") != "ERROR":
        passed, errors = risk_guard(
            nav=data.get("current_price"),
            ma200=data.get("ma200"),
        )
        data["action_allowed"] = passed
        data["recommended_amount"] = data.get("suggested_amount") if passed else None
        data["computed_amount"] = data.get("suggested_amount")
        data["risk_guard_errors"] = errors

    # 查询前十大重仓股
    holdings = session.exec(
        select(FundHolding)
        .where(FundHolding.fund_code == code)
        .order_by(FundHolding.weight.desc())
        .limit(10)
    ).all()
    data["top_holdings"] = [
        {"name": h.stock_name, "code": h.stock_code, "weight": h.weight}
        for h in holdings
    ]
    return data


# 4. 基金自动识别
@app.get("/api/fund/detect/{code}")
def detect_fund(code: str):
    from services.market import auto_detect_fund
    return auto_detect_fund(code)


# 5. v0.8 策略分层视图
@app.get("/api/strategy/framework/{code}")
def get_strategy_framework(code: str, session: Session = Depends(get_session)):
    from services.value_dca import build_decision_report, build_framework_response
    from services.market import get_strategy_advice, risk_guard

    # Get market data + current advice
    mdata = get_strategy_advice(code)
    if mdata.get("action") == "ERROR":
        return {"error": mdata.get("reason", "数据错误")}

    # Get existing strategy params
    dev_pct = (mdata["current_price"] - mdata["ma200"]) / mdata["ma200"] if mdata["ma200"] > 0 else 0
    passed, errors = risk_guard(nav=mdata.get("current_price"), ma200=mdata.get("ma200"))

    # Build report (valuation unknown, 4% dry_run)
    report = build_decision_report(
        fund_code=code, fund_name=mdata.get("name", code),
        source=mdata.get("source", "unknown"),
        nav=mdata.get("current_price"),
        proxy_close=mdata.get("current_price"),
        ma200=mdata.get("ma200"),
        dev_pct=dev_pct,
        role="satellite", thesis="HOLD_OK",
        last_buy_ref=mdata.get("current_price"),  # use current price as reference
        tranches_used=0, tranches_total=10,
        valuation_state="unknown",
        risk_passed=passed, risk_errors=errors,
        computed_amount=mdata.get("suggested_amount", 0),
        action_allowed=passed,
    )
    return build_framework_response(report)


# 6. 交易记录
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
def get_industry_legacy():
    return {"ok": True, "industries": {}, "note": "use /api/portfolio/exposure"}
@app.get("/api/analysis/industry-backup")
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
#    前端静态文件托管
# =======================

# 1. 获取绝对路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")
ASSETS_DIR = os.path.join(DIST_DIR, "assets")

# 2. 挂载静态资源 (CSS/JS/Images)
# 这些文件通常在 /assets 路径下
if os.path.exists(ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")



# ── Health check ──────────────────────────────

@app.get("/api/health")
def health_check(session: Session = Depends(get_session)):
    import os, subprocess
    try: assets_count = len(session.exec(select(Asset)).all())
    except: assets_count = 0
    try: dd_count = len(session.exec(select(DailyDecision).where(DailyDecision.date == _dt.today().isoformat())).all())
    except: dd_count = 0
    git_commit = ""
    try:
        r = subprocess.run("git rev-parse --short HEAD 2>&1", shell=True, capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), timeout=3)
        git_commit = r.stdout.strip()
    except: pass
    db_path = os.environ.get("COMPOUND_DB_PATH", "invest.db")
    db_exists = os.path.exists(db_path)
    db_size = os.path.getsize(db_path) if db_exists else 0
    data_ready = assets_count > 0
    return {
        "service": "backend", "status": "ready" if data_ready else "DEGRADED",
        "service_ready": True, "data_ready": data_ready,
        "version": "v0.9.4",
        "git_commit": git_commit,
        "features": {"exposure_demo": True, "daily_decision": True},
        "db": {"ok": db_exists, "path": db_path, "exists": db_exists,
               "size_bytes": db_size, "asset_count": assets_count,
               "dailydecision_count": dd_count},
        "schema_ready": True,
        "runtime": {"cwd": os.getcwd(), "pid": os.getpid()},
    }


@app.get("/api/runtime/status")
def runtime_status_endpoint(session: Session = Depends(get_session)):
    import os, json, socket
    hb = {}
    hb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hermes", "runtime", ".scheduler_heartbeat.json")
    if os.path.exists(hb_path):
        with open(hb_path) as f: hb = json.load(f)
    frontend_ok = False
    try: s=socket.socket();s.settimeout(1);s.connect(("127.0.0.1",731));s.close();frontend_ok=True
    except: pass
    from datetime import datetime
    hb_alive = hb.get("status")=="alive"
    last_seen=hb.get("last_seen","")
    stale=False
    try: stale=(datetime.now()-datetime.fromisoformat(last_seen)).total_seconds()>300 if last_seen else True
    except: stale=True
    sched_status="IDLE" if hb_alive and not stale else ("DEGRADED" if stale else "STOPPED")
    # Count today's decisions
    try:
        tdy = _dt.today().isoformat()
        decisions = session.exec(select(DailyDecision).where(DailyDecision.date == tdy)).all()
        dd_count = len(decisions)
        srcs = set(d.decision_source for d in decisions if hasattr(d,'decision_source'))
        dd_source = "exposure_demo" if "exposure_demo" in srcs else ("manual" if "manual" in srcs else "scheduler")
    except: dd_count = 0; dd_source = ""
    return {
        "backend":"READY","frontend":"READY" if frontend_ok else "UNKNOWN",
        "scheduler":{"status":sched_status,"alive":hb_alive,"last_heartbeat":last_seen,"next_job":hb.get("next_job",""),"next_job_at":hb.get("next_job_at",""),"last_job":hb.get("last_job",""),"last_job_status":hb.get("last_job_status","")},
        "today":{"status":"generated" if dd_count>0 else "not_generated","decision_count":dd_count,"generated_at":None,"source":dd_source},
    }

# ── v0.8.2 Daily Decision APIs ────────────────────

from db.models import DailyDecision, UserDecision
import json as _json
from datetime import date as _dt, datetime as _datetime


# v0.8.4.2 Exposure demo — generates fixed test data
@app.post("/api/decision/run-exposure-demo")
def run_exposure_demo(session: Session = Depends(get_session)):
    """Generate demo DailyDecision with candidate→final downgrade cases. Never writes transactions."""
    today = _dt.today().isoformat()
    demo = [
        {"fund_code":"000083","fund_name":"汇添富消费行业混合","system_status":"PASS","strategy_action":"fixed_dca",
         "recommended_amount":200,"candidate_amount":200,"downgrade_reason":"","theme_bucket":"消费",
         "reason_summary":"正常定投","classification_source":"AKShare","classification_confidence":"high","decision_source":"exposure_demo"},
        {"fund_code":"001532","fund_name":"华安文体健康混合A","system_status":"PASS","strategy_action":"observe",
         "recommended_amount":0,"candidate_amount":200,"downgrade_reason":"同主题(消费)重复暴露，本周已选择 000083","theme_bucket":"消费",
         "candidate_action":"dynamic_dca","downgraded_from_action":"dynamic_dca","reason_summary":"","classification_source":"local_rule","classification_confidence":"medium","decision_source":"exposure_demo"},
        {"fund_code":"002340","fund_name":"富国价值优势混合A","system_status":"PASS","strategy_action":"review_required",
         "recommended_amount":None,"candidate_amount":200,"downgrade_reason":"组合总额超过上限","theme_bucket":"混合",
         "candidate_action":"dynamic_dca","downgraded_from_action":"dynamic_dca","exposure_status":"REVIEW_REQUIRED","classification_source":"local_rule","classification_confidence":"medium","decision_source":"exposure_demo"},
        {"fund_code":"003096","fund_name":"中欧医疗健康混合C","system_status":"PASS","strategy_action":"observe",
         "recommended_amount":0,"candidate_amount":200,"downgrade_reason":"","theme_bucket":"医药",
         "reason_summary":"估值层未接入，当前仅观察","classification_source":"local_rule","classification_confidence":"medium","decision_source":"exposure_demo"},
        {"fund_code":"005827","fund_name":"易方达蓝筹精选混合","system_status":"PASS","strategy_action":"observe",
         "recommended_amount":0,"candidate_amount":200,"downgrade_reason":"",
         "reason_summary":"估值层未接入，当前仅观察","classification_source":"local_rule","classification_confidence":"medium","decision_source":"exposure_demo"},
    ]
    for c in demo:
        existing = session.exec(select(DailyDecision).where(DailyDecision.date==today,DailyDecision.fund_code==c["fund_code"])).first()
        f = existing if existing else DailyDecision(date=today,fund_code=c["fund_code"],fund_name=c["fund_name"])
        # Set only safe fields (skip decision_source — column may not exist)
        safe_fields = ["system_status","strategy_action","recommended_amount","candidate_amount",
                       "downgrade_reason","candidate_action","downgraded_from_action",
                       "reason_summary","exposure_status","theme_bucket"]
        for k in safe_fields:
            if k in c: setattr(f, k, c[k])
        if not f.theme_bucket or f.theme_bucket == "未分类":
            f.theme_bucket = "消费" if "消费" in c["fund_name"] else ("混合" if "混合" in c["fund_name"] else "医药")
        f.exposure_guard_applied = bool(c.get("downgrade_reason"))
        f.classification_source = c.get("classification_source","local_rule")
        f.classification_confidence = c.get("classification_confidence","medium")
        if not existing: session.add(f)
        else: session.add(f)
        session.commit()
    return {
        "ok": True,
        "decision_source": "exposure_demo",
        "count": len(demo),
        "candidate_total": sum(c.get("candidate_amount",0) or 0 for c in demo),
        "final_total": sum((c.get("recommended_amount") or 0) for c in demo if c["strategy_action"]=="fixed_dca"),
        "items": [{"fund_code":c["fund_code"],"fund_name":c["fund_name"],
                    "candidate_amount":c.get("candidate_amount"),"final_amount":c.get("recommended_amount"),
                    "candidate_action":c.get("candidate_action","fixed_dca"),"final_action":c["strategy_action"],
                    "downgrade_reason":c.get("downgrade_reason","")} for c in demo]
    }


@app.post("/api/decision/run-daily")
def run_daily_decisions(session: Session = Depends(get_session)):
    today = _dt.today().isoformat()
    assets = session.exec(select(Asset)).all()
    candidates = []

    # Phase 1: Collect candidate decisions
    for asset in assets:
        from services.market import get_strategy_advice, risk_guard
        from services.value_dca import evaluate_data_layer, evaluate_price_layer, evaluate_risk_layer
        mdata = get_strategy_advice(asset.code)
        if mdata.get("action") == "ERROR":
            candidates.append({"fund_code": asset.code, "fund_name": asset.name, "system_status": "API_ERROR", "strategy_action": "review_required", "recommended_amount": None, "candidate_amount": None, "error": True})
            continue
        dev_pct = (mdata["current_price"] - mdata["ma200"]) / mdata["ma200"] if mdata["ma200"] > 0 else 0
        passed, errors = risk_guard(nav=mdata.get("current_price"), ma200=mdata.get("ma200"))
        src = mdata.get("source", ""); trusted = src.lower() != "mock"
        data_layer = evaluate_data_layer(mdata.get("current_price"), mdata.get("current_price"), mdata.get("ma200"), src)
        price_layer = evaluate_price_layer(dev_pct)
        ss = "BLOCKED" if (not trusted or not passed or data_layer.blocking) else "PASS"
        if src.lower() == "mock": ss = "BLOCKED"
        grid = mdata.get("grid_pos", 0) or 0
        sa = "review_required" if ss == "BLOCKED" else ("take_profit_watch" if grid > 1 else ("dynamic_dca" if grid < -2 else ("observe" if mdata.get("suggested_amount", 0) == 0 else "fixed_dca")))
        ap = "hide_amount" if ss == "BLOCKED" else ("show_recommended_amount" if passed else "audit_only")
        rec = mdata.get("suggested_amount") if ap == "show_recommended_amount" else None
        candidates.append({
            "fund_code": asset.code, "fund_name": asset.name,
            "system_status": ss, "strategy_action": sa,
            "recommended_amount": rec, "candidate_amount": rec,
            "amount_permission": ap, "dev_pct": dev_pct, "grid_pos": grid,
            "reason_summary": f"grid={grid:.1f}", "risk_reasons": "; ".join(errors),
            "signal_ready": data_layer.status == "READY", "price_position": price_layer.status,
            "risk_guard_passed": passed, "source": src, "trusted": trusted,
            "trace": _json.dumps({"dev_pct": dev_pct, "grid_pos": grid, "computed_amount": mdata.get("suggested_amount", 0), "risk_guard_passed": passed, "source": src}),
            "error": False,
        })

    # Phase 2: Apply exposure guard
    from services.exposure_guard import apply_exposure_guard, classify_theme
    viable = [c for c in candidates if not c["error"]]
    if len(viable) > 1:
        apply_exposure_guard(viable, session)

    # Phase 3: Write to DB
    results = []
    for c in candidates:
        if c.get("error"):
            results.append({"fund_code": c["fund_code"], "status": "API_ERROR"})
            continue
        existing = session.exec(select(DailyDecision).where(DailyDecision.date == today, DailyDecision.fund_code == c["fund_code"])).first()
        f = existing if existing else DailyDecision(date=today, fund_code=c["fund_code"], fund_name=c["fund_name"])
        f.system_status = c["system_status"]; f.strategy_action = c["strategy_action"]
        f.recommended_amount = c.get("recommended_amount")
        f.amount_permission = c.get("amount_permission", "hide_amount")
        f.reason_summary = c.get("reason_summary", "")
        f.risk_reasons = c.get("risk_reasons", "")
        f.signal_ready = c.get("signal_ready", False)
        f.price_position = c.get("price_position", "normal_position")
        f.risk_guard_passed = c.get("risk_guard_passed", True)
        f.source = c.get("source", ""); f.trusted = c.get("trusted", True)
        f.calculation_trace = c.get("trace", "{}")
        # v0.8.3 exposure fields
        f.candidate_amount = c.get("candidate_amount")
        f.final_amount = c.get("recommended_amount")
        f.amount_source = c.get("amount_source", "strategy")
        f.exposure_status = c.get("exposure_status", "PASS")
        f.exposure_reasons = c.get("exposure_reasons", "")
        f.theme_bucket = c.get("theme_bucket", classify_theme(c.get("fund_name", "")))
        f.downgraded_from_action = c.get("downgraded_from_action", "")
        f.downgrade_reason = c.get("downgrade_reason", "")
        f.downgrade_from_fund = c.get("downgrade_from_fund", "")
        f.candidate_action = c.get("downgraded_from_action", "") or c.get("strategy_action", "")
        f.final_action = c.get("strategy_action", "")
        f.exposure_guard_applied = bool(c.get("downgrade_reason") or c.get("exposure_status", "PASS") != "PASS")
        f.classification_source = "local_rule"
        f.classification_confidence = "medium"
        f.holding_date = ""
        if not existing:
            session.add(f)
        else:
            session.add(f)
        session.commit()
        results.append({"fund_code": c["fund_code"], "system_status": c["system_status"], "strategy_action": c["strategy_action"], "downgraded": bool(c.get("downgrade_reason"))})
    return {
        "ok": True,
        "date": today,
        "decision_source": "manual",
        "count": len(results),
        "created": sum(1 for r in results if r.get("status") != "API_ERROR"),
        "summary": {
            "need_action": sum(1 for r in results if r.get("strategy_action")=="fixed_dca"),
            "observe": sum(1 for r in results if r.get("strategy_action")=="observe"),
            "blocked": sum(1 for r in results if r.get("system_status")=="BLOCKED"),
            "total_final_amount": sum((r.get("recommended_amount") or 0) for r in results if r.get("system_status")=="PASS"),
        },
        "results": results
    }


@app.get("/api/decision/today")
def get_today_decisions(session: Session = Depends(get_session)):
    today = _dt.today().isoformat()
    decisions = session.exec(select(DailyDecision).where(DailyDecision.date == today)).all()
    if not decisions:
        return {"date": today, "generated": False, "generated_at": None, "count": 0, "items": [], "reason": "not_generated"}
    items = []
    for d in decisions:
        ud = session.exec(select(UserDecision).where(UserDecision.daily_decision_id == d.id)).first()
        item = {c.name: getattr(d, c.name) for c in d.__table__.columns}
        item["user_action"] = ud.user_action if ud else "pending"
        item["actual_amount"] = ud.actual_amount if ud else None
        item["skip_reason"] = ud.skip_reason if ud else ""
        item["user_note"] = ud.user_note if ud else ""

        # v1.0.3: Enrich with overlap + holding data
        snap = session.exec(select(FundHoldingSnapshot).where(FundHoldingSnapshot.fund_code == d.fund_code).order_by(FundHoldingSnapshot.updated_at.desc())).first()
        if snap:
            stale_days = (_dt.today() - datetime.fromisoformat(snap.holding_date[:10]).date()).days if snap.holding_date else 999
            item["holding_date"] = snap.holding_date
            item["holding_source"] = snap.source
            item["stale_days"] = stale_days
            item["is_fixture"] = snap.source == "local_heuristic"
            item["usable_for_live"] = not item["is_fixture"] and stale_days <= 120
        else:
            item["holding_date"] = None
            item["holding_source"] = None
            item["stale_days"] = None
            item["is_fixture"] = False
            item["usable_for_live"] = False

        # Find overlap with actionable funds
        actionable = [dd for dd in decisions if dd.strategy_action in ("fixed_dca", "dynamic_dca") and dd.fund_code != d.fund_code]
        if actionable:
            snap_b = session.exec(select(FundHoldingSnapshot).where(FundHoldingSnapshot.fund_code == actionable[0].fund_code).order_by(FundHoldingSnapshot.updated_at.desc())).first()
            if snap and snap_b:
                from services.exposure_calculator import compute_fund_pair_overlap
                overlap = compute_fund_pair_overlap(
                    {"top10_json": snap.top10_json, "industry_distribution_json": snap.industry_distribution_json},
                    {"top10_json": snap_b.top10_json, "industry_distribution_json": snap_b.industry_distribution_json})
                item["overlap_status"] = overlap["overlap_level"]
                item["overlap_score"] = overlap["top10_overlap_score"]
                item["overlap_industry"] = overlap["industry_overlap_score"]
                item["overlap_evidence"] = overlap.get("evidence", [])
                # v1.2: coverage + scope fields
                item["coverage_level"] = overlap.get("coverage_level", "top10_only")
                item["overlap_scope"] = overlap.get("overlap_scope", "heavy_position_only")
                item["stock_weight_coverage"] = getattr(snap, "stock_weight_coverage", 0) if snap else 0
                item["heavy_position_overlap_level"] = overlap.get("heavy_position_overlap_level")
                item["industry_status"] = overlap.get("industry_status", "ok")
                item["live_overlap_level"] = overlap.get("live_overlap_level", "unknown")
                item["full_exposure_ready"] = False
                item["limitation"] = overlap.get("limitation", "仅基于前十大持仓，可能低估中尾部重叠")
                item["common_holdings"] = overlap.get("common_holdings", [])
                item["human_review_reason"] = "Top10 重仓股存在重叠，进入观察/人工复核；不直接改变建议金额。" if overlap.get("overlap_level") in ("medium","high") else ""
            else:
                item["overlap_status"] = "DATA_MISSING"
                item["coverage_level"] = "unknown"
                item["overlap_scope"] = "none"
                item["heavy_position_overlap_level"] = None
                item["industry_status"] = "INDUSTRY_DATA_MISSING"
                item["limitation"] = "持仓数据缺失，无法计算重叠"
                item["common_holdings"] = []
        else:
            item["overlap_status"] = "N/A"
            item["coverage_level"] = "N/A"
            item["overlap_scope"] = "N/A"
            item["heavy_position_overlap_level"] = None
            item["industry_status"] = "N/A"
            item["limitation"] = "无可比对的基金对"
            item["common_holdings"] = []

        items.append(item)
    # ── v1.3: Decision action mapping ─────────────────
    for item in items:
        sa = item.get("strategy_action", "")
        dr = item.get("downgrade_reason", "")
        # Map to decision_action
        if sa in ("fixed_dca", "dynamic_dca"):
            item["decision_action"] = "BUY"; item["amount_display_policy"] = "SHOW_AMOUNT"
            item["user_action_policy"] = "CAN_MARK_DONE"; item["can_mark_done"] = True
            item["can_skip"] = True; item["can_override"] = False; item["override_requires_reason"] = False
        elif sa == "blocked" or item.get("exposure_status") == "BLOCKED":
            item["decision_action"] = "BLOCKED"; item["amount_display_policy"] = "HIDE_AMOUNT"
            item["user_action_policy"] = "DISABLED"; item["can_mark_done"] = False
            item["can_skip"] = False; item["can_override"] = False
        elif dr and ("重叠" in dr or "top10" in dr.lower() or "overlap" in dr.lower() or "exposure" in dr.lower()):
            item["decision_action"] = "REVIEW_REQUIRED"; item["amount_display_policy"] = "AUDIT_ONLY"
            item["user_action_policy"] = "REQUIRE_REVIEW_NOTE"; item["can_mark_done"] = False
            item["can_skip"] = True; item["can_override"] = True; item["override_requires_reason"] = True
        elif sa == "take_profit_watch" or "WATCH" in str(item.get("exposure_status", "")):
            item["decision_action"] = "WATCH"; item["amount_display_policy"] = "SHOW_ZERO"
            item["user_action_policy"] = "CAN_SKIP"; item["can_mark_done"] = False
            item["can_skip"] = True; item["can_override"] = False
        elif sa == "observe":
            item["decision_action"] = "OBSERVE"; item["amount_display_policy"] = "SHOW_ZERO"
            item["user_action_policy"] = "CAN_SKIP"; item["can_mark_done"] = False
            item["can_skip"] = True; item["can_override"] = False
        else:
            item["decision_action"] = "NO_ACTION"; item["amount_display_policy"] = "HIDE_AMOUNT"
            item["user_action_policy"] = "DISABLED"; item["can_mark_done"] = False
            item["can_skip"] = False; item["can_override"] = False
        # Execution status
        ua = item.get("user_action", "pending")
        item["execution_status"] = "DONE" if ua == "done" else ("SKIPPED" if ua == "skipped" else "PENDING")
        # Required user input
        if item["decision_action"] == "REVIEW_REQUIRED":
            item["required_user_input"] = "复核原因（必填）"
        elif item["decision_action"] in ("BUY", "OBSERVE", "WATCH"):
            item["required_user_input"] = ""
        else:
            item["required_user_input"] = ""
        # amount visibility
        fin = item.get("recommended_amount", 0) or 0
        if item["amount_display_policy"] == "SHOW_AMOUNT":
            item["final_amount"] = fin
        elif item["amount_display_policy"] == "SHOW_ZERO":
            item["final_amount"] = 0
        elif item["amount_display_policy"] == "AUDIT_ONLY":
            item["final_amount"] = None; item["audit_amount"] = fin
        else:
            item["final_amount"] = None
    # ── v1.5: Valuation enrichment ──────────────────────
    from services.valuation import fetch_valuation
    for item in items:
        val = fetch_valuation(item["fund_code"])
        item.update({f"valuation_{k}": v for k, v in val.items()})
        # v1.5.1: Only trigger REVIEW_REQUIRED when proxy is confident
        vlevel = val.get("valuation_level")
        vstatus = val.get("proxy_status", "ok")
        is_weak = vstatus in ("weak_proxy", "bond_pending")
        if vlevel == "expensive" and item["decision_action"] == "BUY" and not is_weak:
            item["decision_action"] = "REVIEW_REQUIRED"
            item["amount_display_policy"] = "AUDIT_ONLY"
            item["valuation_action"] = "REVIEW_REQUIRED"
            item["valuation_reason"] = "估值偏高但策略建议买入，需人工复核"
        elif vlevel == "undervalued" and item["decision_action"] in ("OBSERVE", "WATCH") and not is_weak:
            item["valuation_action"] = "WATCH"
            item["valuation_reason"] = "估值偏低但策略未建议买入，需关注"
        elif is_weak and item.get("valuation_proxy_status") != "bond_pending":
            item["valuation_action"] = "INFO_ONLY"
            item["valuation_reason"] = "估值代理较弱(仅参考)"
    first = min(items, key=lambda x: x.get("created_at", "")) if items else None
    return {"date": today, "generated": True, "generated_at": str(first.get("created_at", "")) if first else None, "count": len(items), "items": items}


@app.post("/api/decision/{decision_id}/ack")
def ack_decision(decision_id: int, session: Session = Depends(get_session)):
    ud = session.exec(select(UserDecision).where(UserDecision.daily_decision_id == decision_id)).first()
    if not ud: ud = UserDecision(daily_decision_id=decision_id, user_action="acknowledged")
    else: ud.user_action = "acknowledged"
    session.add(ud); session.commit(); return {"ok": True}


@app.post("/api/decision/{decision_id}/user-action")
def record_user_action(decision_id: int, data: dict, session: Session = Depends(get_session)):
    dd = session.get(DailyDecision, decision_id)
    if not dd: return {"ok": False, "error": "Decision not found"}

    ud = session.exec(select(UserDecision).where(UserDecision.daily_decision_id == decision_id)).first()
    if not ud: ud = UserDecision(daily_decision_id=decision_id)
    action = data.get("action", "pending")
    ud.user_action = action
    ud.actual_amount = data.get("actual_amount")
    ud.skip_reason = data.get("skip_reason", "")
    ud.user_note = data.get("user_note", "")
    ud.review_note = data.get("review_note", "")
    ud.override_reason = data.get("override_reason", "")

    # v1.4: Pool deduction guard — only BUY + executed allows transaction/pool deduction
    is_buy = dd.strategy_action in ("fixed_dca", "dynamic_dca")
    if action == "executed" and is_buy:
        ud.confirmed_at = _datetime.now()
        # Only deduct pool for BUY executed
    elif action == "executed" and not is_buy:
        return {"ok": False, "error": "NON_BUY_EXECUTED_BLOCKED", "reason": "Only BUY items can be marked as executed"}
    elif action in ("skipped", "observed", "acknowledged", "reviewed"):
        ud.confirmed_at = _datetime.now()

    session.add(ud); session.commit()
    return {"ok": True, "action": action, "pool_deductible": action == "executed" and is_buy}


@app.get("/api/decision/history")
def get_decision_history(days: int = 7, session: Session = Depends(get_session)):
    from datetime import timedelta
    start = (_dt.today() - timedelta(days=days)).isoformat()
    return session.exec(select(DailyDecision).where(DailyDecision.date >= start).order_by(DailyDecision.date.desc())).all()


# 3. 🔥 核心修复：处理根路径 "/" 和所有其他前端路由 🔥
# 注意：这个函数必须放在所有 @app.get("/api/...") 之后！
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    # 如果是 API 请求但没匹配到上面的接口，返回 404
    if full_path.startswith("api/"):
        return {"error": "API endpoint not found"}

    # 否则，一律返回 index.html (让 React 路由去处理页面跳转)
    index_file = os.path.join(DIST_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    else:
        return {
            "error": "前端文件未找到",
            "tip": "请确保你已经执行了 'npm run build' 并将 'dist' 文件夹放到了 'backend' 目录下。",
        }



# v1.0 AI Exposure Analyst APIs
from db.models import FundHoldingSnapshot, FundExposureAnalysis, FundOverlap

@app.post('/api/analysis/exposure/run/{fund_code}')
def run_exposure_analysis(fund_code: str, session: Session = Depends(get_session)):
    from services.ai_exposure_analyst import analyze_fund_exposure
    asset = session.exec(select(Asset).where(Asset.code == fund_code)).first()
    if not asset: return {'ok':False,'error':'Fund not found'}
    fund_data = {'fund_code':fund_code,'fund_name':asset.name,'top10':[],'industry_distribution':{}}
    result = analyze_fund_exposure(fund_data,'')
    f = FundExposureAnalysis(fund_code=fund_code,primary_theme=result.get('primary_theme',''),
        theme_bucket=result.get('theme_bucket',''),classification_source=result.get('classification_source',''),
        classification_confidence=result.get('confidence',''),evidence_json=json.dumps(result.get('evidence',[])),
        uncertainty_json=json.dumps(result.get('uncertainty',[])),model_name=result.get('model_name',''),
        prompt_hash=result.get('prompt_hash',''),input_hash=result.get('input_hash',''))
    session.add(f); session.commit()
    return {'ok':True,'fund_code':fund_code,'analysis':result}

@app.post('/api/analysis/exposure/run-all')
def run_all_exposure(session: Session = Depends(get_session)):
    assets = session.exec(select(Asset)).all()
    results = {}
    for a in assets:
        try:
            r = run_exposure_analysis(a.code, session)
            results[a.code] = r.get('analysis',{}).get('primary_theme','error')
        except: results[a.code] = 'error'
    return {'ok':True,'results':results}

@app.get('/api/analysis/exposure/{fund_code}')
def get_exposure(fund_code: str, session: Session = Depends(get_session)):
    analyses = session.exec(select(FundExposureAnalysis).where(FundExposureAnalysis.fund_code==fund_code).order_by(FundExposureAnalysis.created_at.desc())).all()
    if not analyses: return {'ok':True,'fund_code':fund_code,'analysis':None}
    a = analyses[0]
    return {'ok':True,'fund_code':fund_code,'analysis':{'primary_theme':a.primary_theme,'theme_bucket':a.theme_bucket,'source':a.classification_source,'confidence':a.classification_confidence,'evidence':json.loads(a.evidence_json),'uncertainty':json.loads(a.uncertainty_json),'model':a.model_name}}

@app.get('/api/portfolio/exposure')
def portfolio_exposure(session: Session = Depends(get_session)):
    analyses = session.exec(select(FundExposureAnalysis).order_by(FundExposureAnalysis.created_at.desc())).all()
    themes = {}
    for a in analyses:
        tb = a.theme_bucket or '未分类'
        themes[tb] = themes.get(tb,0) + 1
    return {'ok':True,'theme_exposure':themes}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9600)
