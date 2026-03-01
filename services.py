"""
SmartInvest 业务逻辑层
- 行情获取（东财/腾讯/Yahoo 多源回退）
- 网格策略引擎
- 组合调度 + 双重刹车
- 基金持仓穿透
"""

import os
import time
import math
import random
import logging
import contextlib
from datetime import date, datetime
from collections import defaultdict

import requests
import pandas as pd
import numpy as np
import yfinance as yf
import akshare as ak
from sqlmodel import Session, select, delete

logger = logging.getLogger("smartinvest.services")

# =============================================
#  1. 行情获取（多数据源 + 缓存）
# =============================================

_market_cache = {}
CACHE_DURATION = 600


@contextlib.contextmanager
def force_no_proxy():
    saved = {}
    for key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
        if key in os.environ:
            saved[key] = os.environ[key]
            del os.environ[key]
    try:
        yield
    finally:
        for key, value in saved.items():
            os.environ[key] = value


def fetch_fund_mobile_api(code: str, use_proxy: bool):
    """东方财富 APP 历史净值接口"""
    url = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList"
    params = {
        "FCODE": code, "pageIndex": "1", "pageSize": "300",
        "plat": "Android", "product": "EFund", "version": "6.3.8",
        "deviceid": "1", "appType": "ttjj",
    }
    headers = {
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 10; Pixel 4 Build/QD1A.190821.007)",
        "Host": "fundmobapi.eastmoney.com",
        "Referer": "https://fund.eastmoney.com",
    }
    proxies_conf = {"http": None, "https": None} if not use_proxy else None
    mode = "VPN" if use_proxy else "直连"

    try:
        if not use_proxy:
            with force_no_proxy():
                res = requests.get(url, params=params, headers=headers, proxies=proxies_conf, timeout=6)
        else:
            res = requests.get(url, params=params, headers=headers, timeout=6)

        res.raise_for_status()
        data = res.json()
        datas = data.get("Datas")
        if not datas:
            return None

        rows = []
        for item in datas:
            try:
                rows.append({"date": item["FSRQ"], "close": float(item["DWJZ"])})
            except Exception:
                pass
        if not rows:
            return None

        rows.reverse()
        logger.info(f"[Eastmoney基金] {code} ({mode}) 拿到 {len(rows)} 条")
        return pd.DataFrame(rows)
    except Exception as e:
        logger.warning(f"[Eastmoney基金] {code} ({mode}) 失败: {e}")
        return None


def fetch_fund_tencent(code: str):
    """腾讯财经净值接口"""
    url = "http://web.ifzq.gtimg.cn/fund/newfund/fundSjk/getSjk"
    params = {"symbol": f"jj{code}", "startDate": "20200101", "limit": 300}
    try:
        with force_no_proxy():
            res = requests.get(url, params=params, proxies={"http": None, "https": None}, timeout=6)
            res.raise_for_status()
            data = res.json()
            if data and data.get("data"):
                k_data = data["data"].get(f"jj{code}")
                if k_data:
                    rows = []
                    for item in k_data:
                        d_str = str(item[0])
                        d_fmt = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:]}"
                        rows.append({"date": d_fmt, "close": float(item[1])})
                    if rows:
                        logger.info(f"[腾讯基金] {code} 拿到 {len(rows)} 条")
                        return pd.DataFrame(rows)
    except Exception as e:
        logger.warning(f"[腾讯基金] {code} 失败: {e}")
    return None


def fetch_mutual_fund(code: str):
    """场外基金：东财APP → 腾讯 → 东财VPN"""
    df = fetch_fund_mobile_api(code, use_proxy=False)
    if df is not None:
        return df
    df = fetch_fund_tencent(code)
    if df is not None:
        return df
    return fetch_fund_mobile_api(code, use_proxy=True)


def fetch_eastmoney_etf(code: str):
    """场内 ETF/股票：东财 K 线接口"""
    raw_code = code.replace("sh", "").replace("sz", "")
    secid = f"1.{raw_code}" if code.startswith("sh") else f"0.{raw_code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid, "fields1": "f1", "fields2": "f51,f53",
        "klt": "101", "fqt": "1", "end": "20500101", "lmt": "300",
    }

    for use_proxy in [False, True]:
        try:
            if not use_proxy:
                with force_no_proxy():
                    res = requests.get(url, params=params, proxies={"http": None, "https": None}, timeout=5)
            else:
                res = requests.get(url, params=params, timeout=5)
            res.raise_for_status()
            data = res.json()
            if data.get("data") and data["data"].get("klines"):
                rows = []
                for line in data["data"]["klines"]:
                    arr = line.split(",")
                    rows.append({"date": arr[0], "close": float(arr[1])})
                df = pd.DataFrame(rows)
                if not df.empty:
                    mode = "VPN" if use_proxy else "直连"
                    logger.info(f"[Eastmoney ETF] {code} ({mode}) 拿到 {len(df)} 条")
                    return df
        except Exception as e:
            mode = "VPN" if use_proxy else "直连"
            logger.warning(f"[Eastmoney ETF] {code} ({mode}) 失败: {e}")
    return None


def fetch_from_yahoo(code: str):
    """Yahoo Finance 备选源"""
    raw_code = code.replace("sh", "").replace("sz", "")
    y_code = f"{raw_code}.SS" if "sh" in code else f"{raw_code}.SZ"
    try:
        df = yf.download(y_code, period="1y", interval="1d", auto_adjust=True, progress=False, timeout=8)
        if not df.empty:
            df = df.reset_index()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [str(c).lower() for c in df.columns]
            logger.info(f"[Yahoo] {code} 拿到 {len(df)} 条")
            return df
    except Exception as e:
        logger.warning(f"[Yahoo] {code} 失败: {e}")
    return None


def get_strategy_advice(code: str, name: str = "未知标的"):
    """核心调度：获取行情 → 计算技术指标 → 返回结构化数据"""
    global _market_cache
    current_time = time.time()

    if code in _market_cache:
        cached = _market_cache[code]
        if current_time - cached["timestamp"] < CACHE_DURATION:
            return cached["data"]

    is_etf = "sh" in code or "sz" in code
    df = None
    if is_etf:
        df = fetch_eastmoney_etf(code)
        if df is None:
            df = fetch_from_yahoo(code)
    else:
        df = fetch_mutual_fund(code)

    if df is None or df.empty:
        return {"fund_code": code, "name": name, "action": "ERROR", "reason": "数据源连接失败", "history": []}

    try:
        df.columns = [str(c).lower() for c in df.columns]
        if "fsrq" in df.columns:
            df.rename(columns={"fsrq": "date", "dwjz": "close"}, inplace=True)
        if "date" not in df.columns:
            for col in ["Date", "datetime"]:
                if col in df.columns:
                    df.rename(columns={col: "date"}, inplace=True)
        if "close" not in df.columns:
            for col in ["Close", "price"]:
                if col in df.columns:
                    df.rename(columns={col: "close"}, inplace=True)

        df["date"] = pd.to_datetime(df["date"])
        df["close"] = pd.to_numeric(df["close"])
        df = df.sort_values(by="date")
        df["ma200"] = df["close"].rolling(window=200).mean()
        df["log_ret"] = np.log(df["close"] / df["close"].shift(1))
        df["volatility_60"] = df["log_ret"].rolling(window=60).std()

        latest = df.iloc[-1]
        curr = float(latest["close"])
        ma200 = float(latest["ma200"]) if pd.notna(latest["ma200"]) else curr
        vol_daily = float(latest["volatility_60"]) if pd.notna(latest["volatility_60"]) else 0.015

        hist = []
        for _, row in df.tail(250).iterrows():
            hist.append({
                "date": row["date"].strftime("%Y-%m-%d"),
                "price": row["close"],
                "ma200": row["ma200"] if pd.notna(row["ma200"]) else None,
            })

        result = {
            "fund_code": code, "name": name,
            "current_price": round(curr, 4), "ma200": round(ma200, 4),
            "vol_daily": vol_daily, "history": hist, "action": "CALCULATING",
        }
        _market_cache[code] = {"data": result, "timestamp": current_time}
        return result
    except Exception as e:
        return {"fund_code": code, "action": "ERROR", "reason": str(e)}


# =============================================
#  2. 网格策略引擎
# =============================================

WEEKLY_BUDGET = 200.0
MAX_SINGLE_MULTIPLIER = 5.0


def calculate_grid_logic(current_price, ma200, vol_daily, reserve_balance):
    """核心算法 v2.1：线性插值 + 几何网格"""
    if ma200 <= 0:
        return "mid", 0, 0, 0, 0, "数据不足"

    vol_weekly = vol_daily * 2.236
    grid_width = max(vol_weekly * 0.6, 0.005)
    deviation = (current_price - ma200) / ma200
    grid_pos = deviation / grid_width

    base_amt = WEEKLY_BUDGET
    final_invest = 0.0
    to_reserve = 0.0
    from_reserve = 0.0
    level = "mid"
    reasons = []

    if grid_pos >= 2.0:
        level = "high"
        to_reserve = base_amt
        final_invest = 0
        reasons.append(f"高估{grid_pos:.1f}格，暂停定投，全额蓄力")
    elif grid_pos > -2.0:
        level = "mid"
        if grid_pos <= 0:
            ratio = 1.0
            reasons.append(f"中低区({grid_pos:.1f}格)，标准定投")
        else:
            ratio = max(0.0, 1.0 - grid_pos * 0.5)
            reasons.append(f"中高区({grid_pos:.1f}格)，投入收缩至{ratio*100:.0f}%")
        final_invest = base_amt * ratio
        to_reserve = base_amt - final_invest
    else:
        level = "low"
        extra_grids = abs(grid_pos) - 2.0
        multiplier = min(1.5 * (1.2 ** extra_grids), MAX_SINGLE_MULTIPLIER)
        if multiplier >= MAX_SINGLE_MULTIPLIER:
            reasons.append("触及单次倍数上限")

        target_amt = base_amt * multiplier
        if target_amt <= base_amt:
            final_invest = target_amt
        else:
            needed_extra = target_amt - base_amt
            if needed_extra <= reserve_balance:
                from_reserve = needed_extra
                final_invest = target_amt
                reasons.append(f"低估{grid_pos:.1f}格，{multiplier:.1f}倍加码")
            else:
                from_reserve = reserve_balance
                final_invest = base_amt + from_reserve
                reasons.append(f"低估{grid_pos:.1f}格，弹药耗尽全力买入")

    return level, final_invest, to_reserve, from_reserve, grid_pos, ", ".join(reasons)


def get_instant_analysis(code: str, session: Session):
    """实时策略分析（不写入 DB，但读取真实资金池余额）"""
    from main import FundHolding

    mdata = get_strategy_advice(code)
    if mdata.get("action") == "ERROR":
        return mdata

    pool_balance = _get_global_state(session).pool_balance

    level, invest, to_res, from_res, grid_pos, reason = calculate_grid_logic(
        mdata["current_price"], mdata["ma200"], mdata["vol_daily"], pool_balance
    )
    action_str = "BUY" if invest > 0 else ("WAIT" if level == "high" else "SELL")

    mdata.update({
        "action": action_str,
        "suggested_amount": round(invest, 0),
        "reason": f"网格: {grid_pos:.1f} ({reason})",
        "grid_pos": grid_pos,
        "pool_balance": pool_balance,
        "from_reserve": round(from_res, 2),
        "to_reserve": round(to_res, 2),
    })

    holdings = session.exec(
        select(FundHolding).where(FundHolding.fund_code == code)
        .order_by(FundHolding.weight.desc()).limit(10)
    ).all()
    mdata["top_holdings"] = [{"name": h.stock_name, "code": h.stock_code, "weight": h.weight} for h in holdings]

    return mdata


def run_strategy_analysis(code: str, session: Session):
    """执行单标的策略：读取真实资金池 → 计算 → 更新资金池 → 写 DailyPlan"""
    from main import FundState, DailyPlan

    mdata = get_strategy_advice(code)
    if mdata.get("action") == "ERROR":
        raise Exception(mdata.get("reason"))

    plan_state = _get_global_state(session)
    reserve_before = plan_state.pool_balance

    level, invest, to_res, from_res, grid_pos, reason = calculate_grid_logic(
        mdata["current_price"], mdata["ma200"], mdata["vol_daily"], reserve_before
    )

    # 资金池真实变动：高估蓄力 +to_res，低估动用 -from_res
    reserve_after = reserve_before + to_res - from_res
    plan_state.pool_balance = reserve_after
    session.add(plan_state)

    fund_state = session.exec(select(FundState).where(FundState.asset_code == code)).first()
    if not fund_state:
        fund_state = FundState(asset_code=code, cumulative_reserve_usage=0.0)
        session.add(fund_state)
        session.commit()
        session.refresh(fund_state)

    fund_state.cumulative_reserve_usage += from_res - to_res
    fund_state.last_signal_date = date.today().isoformat()
    session.add(fund_state)

    today_str = date.today().isoformat()
    existing = session.exec(
        select(DailyPlan).where(DailyPlan.asset_code == code, DailyPlan.date == today_str)
    ).first()
    if existing:
        session.delete(existing)

    plan = DailyPlan(
        asset_code=code, date=today_str,
        close=mdata["current_price"], ma200=mdata["ma200"],
        dev_pct=grid_pos, level=level,
        base_amt=WEEKLY_BUDGET,
        dyn_amt=from_res if from_res > 0 else -to_res,
        total_amt=invest,
        reserve_before=reserve_before,
        reserve_after=reserve_after,
    )
    session.add(plan)
    session.commit()

    return {
        "date": today_str, "level": level, "grid_pos": f"{grid_pos:.1f}",
        "advice": f"建议买入 ¥{invest:.0f}", "details": reason,
        "pool_before": reserve_before, "pool_after": reserve_after,
    }


def generate_weekly_report_text(code: str, session: Session, days: int = 7):
    """生成策略复盘报告"""
    from main import DailyPlan  # 延迟导入

    plans = session.exec(
        select(DailyPlan).where(DailyPlan.asset_code == code)
        .order_by(DailyPlan.date.desc()).limit(days)
    ).all()
    if not plans:
        return "无数据"
    plans = plans[::-1]
    last = plans[-1]

    if last.total_amt == 0:
        action_desc = f"🛑 暂停定投，本周预算 ¥{abs(last.dyn_amt):.0f} 存入准备金"
    elif last.dyn_amt > 0:
        action_desc = f"🚀 加码定投 ¥{last.total_amt:.0f} (含备用金 ¥{last.dyn_amt:.0f})"
    elif last.dyn_amt < 0:
        action_desc = f"⚖️ 减额定投 ¥{last.total_amt:.0f} (结余 ¥{abs(last.dyn_amt):.0f} 存入准备金)"
    else:
        action_desc = f"✅ 标准定投 ¥{last.total_amt:.0f}"

    return f"""
**[{code}] 策略复盘 ({plans[0].date} ~ {last.date})**
-------------------
📊 **网格位置**：{last.dev_pct:.1f} 格
💰 **本周投入**：¥{last.total_amt:.0f}
📝 **执行动作**：{action_desc}
🏦 **准备金池**：¥{last.reserve_after:.0f}
    """


# =============================================
#  3. 组合调度 + 双重刹车
# =============================================

MIN_TRADE_AMOUNT = 50.0


def adjust_pool_balance(session: Session, amount: float, operation: str = "DEPOSIT"):
    """资金池充值/提现"""
    from main import PlanState  # 延迟导入
    state = _get_global_state(session)
    if operation == "DEPOSIT":
        state.pool_balance += amount
    elif operation == "WITHDRAW":
        state.pool_balance -= amount
    session.add(state)
    session.commit()
    session.refresh(state)
    return state


def _get_global_state(session: Session):
    """获取或初始化全局状态"""
    from main import PlanState  # 延迟导入
    state = session.exec(select(PlanState).where(PlanState.id == 1)).first()
    if not state:
        state = PlanState(id=1, pool_balance=0.0, base_investment=200.0, deposit_frequency="MANUAL")
        session.add(state)
        session.commit()
        session.refresh(state)
    return state


def run_portfolio_strategy(session: Session):
    """
    一键执行全组合策略：
    1. 读取真实资金池余额
    2. 按网格低估度排序、双重刹车
    3. 从池中分配资金（低估加码消耗弹药，高估蓄力回补弹药）
    4. 写 DailyPlan 留痕，更新资金池余额
    """
    from main import Asset, Transaction, IndustryLimit, DailyPlan

    plan_state = _get_global_state(session)
    pool_before = plan_state.pool_balance
    assets = session.exec(select(Asset)).all()

    industry_limits_db = session.exec(select(IndustryLimit)).all()
    industry_limits = {il.industry: il.max_weight for il in industry_limits_db}

    def get_ind_limit(ind):
        return industry_limits.get(ind, 0.3)

    candidates = []
    total_market_value = 0.0
    global_industry_mv = defaultdict(float)

    for asset in assets:
        mdata = get_strategy_advice(asset.code, asset.name)
        if mdata.get("action") == "ERROR":
            continue

        txs = session.exec(select(Transaction).where(Transaction.asset_code == asset.code)).all()
        units = sum(t.units for t in txs if t.type == "BUY") - sum(t.units for t in txs if t.type == "SELL")
        current_mv = units * mdata["current_price"]
        total_market_value += current_mv

        ind_vector = get_fund_industry_vector(session, asset.code)
        if ind_vector:
            for ind, weight in ind_vector.items():
                global_industry_mv[ind] += current_mv * weight

        level, _, _, _, grid_pos, reason = calculate_grid_logic(
            mdata["current_price"], mdata["ma200"], mdata["vol_daily"], pool_before
        )
        candidates.append({
            "asset": asset, "mdata": mdata, "grid_pos": grid_pos,
            "current_mv": current_mv, "ind_vector": ind_vector, "level": level,
        })

    total_net_worth = max(total_market_value + pool_before, 1000)
    candidates.sort(key=lambda x: x["grid_pos"])

    suggestions = []
    sim_pool = pool_before
    today_str = date.today().isoformat()
    total_to_reserve = 0.0

    for item in candidates:
        asset = item["asset"]
        grid = item["grid_pos"]
        current_mv = item["current_mv"]
        ind_vector = item.get("ind_vector")
        mdata = item["mdata"]

        brake_factor = 1.0
        brake_reasons = []

        current_weight = current_mv / total_net_worth
        max_weight = getattr(asset, "max_weight_limit", 0.2)
        if current_weight >= max_weight:
            brake_factor = 0.0
            brake_reasons.append(f"单标仓位({current_weight*100:.1f}%)超限")
        elif current_weight >= max_weight * 0.8:
            brake_factor = min(brake_factor, 1.0 - (current_weight - max_weight * 0.8) / (max_weight * 0.2))
            brake_reasons.append("单标接近上限")

        if ind_vector and brake_factor > 0:
            for ind, w in ind_vector.items():
                ind_mv = global_industry_mv.get(ind, 0.0)
                ind_ratio = ind_mv / total_net_worth
                ind_limit = get_ind_limit(ind)
                if ind_ratio >= ind_limit:
                    brake_factor = 0.0
                    brake_reasons.append(f"行业[{ind}]({ind_ratio*100:.1f}%)超限")
                    break
                elif ind_ratio >= ind_limit * 0.8:
                    brake_factor = min(brake_factor, 1.0 - (ind_ratio - ind_limit * 0.8) / (ind_limit * 0.2))
                    brake_reasons.append(f"行业[{ind}]接近上限")

        actual_invest = 0.0
        dyn_amt = 0.0

        if brake_factor == 0:
            suggestions.append({"code": asset.code, "name": asset.name, "amt": 0,
                                "msg": f"🚫 禁买: {'; '.join(brake_reasons)}"})
        elif grid > 2.0:
            # 高估蓄力：本期 base_investment 回补弹药池
            saved = plan_state.base_investment
            total_to_reserve += saved
            dyn_amt = -saved
            suggestions.append({"code": asset.code, "name": asset.name, "amt": 0,
                                "msg": f"📉 高估({grid:.1f}格)，¥{saved:.0f} 蓄入弹药池"})
        else:
            multiplier = 1.0
            if grid <= -2.0:
                multiplier = 1.5 * (1.2 ** (abs(grid) - 2.0))
            elif grid > 0:
                multiplier = 1.0 - grid * 0.5

            target_amt = plan_state.base_investment * multiplier * brake_factor
            actual_invest = min(target_amt, sim_pool)

            if actual_invest >= MIN_TRADE_AMOUNT:
                actual_invest = round(actual_invest / 10) * 10
                from_reserve = max(0, actual_invest - plan_state.base_investment)
                dyn_amt = from_reserve
                sim_pool -= actual_invest
                msg = f"网格{grid:.1f}，建议买入"
                if from_reserve > 0:
                    msg += f" (动用弹药 ¥{from_reserve:.0f})"
                if brake_reasons:
                    msg += f" (⚠️ {'; '.join(brake_reasons)})"
                suggestions.append({"code": asset.code, "name": asset.name, "amt": actual_invest, "msg": msg})
            elif actual_invest > 0:
                suggestions.append({"code": asset.code, "name": asset.name, "amt": 0, "msg": "金额不足起投"})
            else:
                suggestions.append({"code": asset.code, "name": asset.name, "amt": 0, "msg": "无需操作"})

        # 写 DailyPlan 留痕
        existing = session.exec(
            select(DailyPlan).where(DailyPlan.asset_code == asset.code, DailyPlan.date == today_str)
        ).first()
        if existing:
            session.delete(existing)

        session.add(DailyPlan(
            asset_code=asset.code, date=today_str,
            close=mdata["current_price"], ma200=mdata["ma200"],
            dev_pct=grid, level=item["level"],
            base_amt=plan_state.base_investment, dyn_amt=dyn_amt,
            total_amt=actual_invest,
            reserve_before=pool_before, reserve_after=sim_pool + total_to_reserve,
        ))

    # 高估蓄力回补到池中，投资消耗已在 sim_pool 中扣除
    pool_after = sim_pool + total_to_reserve
    plan_state.pool_balance = pool_after
    session.add(plan_state)
    session.commit()

    return {
        "suggestions": suggestions,
        "pool_before": pool_before,
        "pool_after": pool_after,
        "total_invested": pool_before - sim_pool,
        "total_saved": total_to_reserve,
    }


# =============================================
#  4. 基金持仓穿透
# =============================================

def fetch_holdings_akshare(code: str):
    """使用 AKShare 获取基金持仓"""
    from main import Stock, FundHolding  # 延迟导入
    symbol = code.replace("sh", "").replace("sz", "")
    current_year = datetime.now().year

    try:
        with force_no_proxy():
            df = ak.fund_portfolio_hold_em(symbol=symbol, date=str(current_year))
            if df is None or df.empty:
                df = ak.fund_portfolio_hold_em(symbol=symbol, date=str(current_year - 1))

        if df is None or df.empty:
            return None, None

        latest_quarter = sorted(df["季度"].unique(), reverse=True)[0]
        df_latest = df[df["季度"] == latest_quarter]

        rows = []
        for _, row in df_latest.iterrows():
            rows.append({
                "stock_code": str(row["股票代码"]),
                "stock_name": str(row["股票名称"]),
                "industry": "未分类",
                "weight": float(row["占净值比例"]) / 100.0,
            })
        return rows, latest_quarter
    except Exception as e:
        logger.warning(f"AKShare 获取持仓异常: {e}")
        return None, None


def sync_fund_holdings(session: Session, fund_code: str):
    """同步单只基金的持仓到数据库"""
    from main import Stock, FundHolding  # 延迟导入

    holdings, report_date = fetch_holdings_akshare(fund_code)
    if not holdings:
        return

    session.exec(delete(FundHolding).where(FundHolding.fund_code == fund_code))

    for item in holdings:
        stock = session.exec(select(Stock).where(Stock.code == item["stock_code"])).first()
        if not stock:
            stock = Stock(code=item["stock_code"], name=item["stock_name"], industry=item["industry"])
            session.add(stock)
        fh = FundHolding(
            fund_code=fund_code, stock_code=item["stock_code"],
            stock_name=item["stock_name"], weight=item["weight"], report_date=report_date,
        )
        session.add(fh)
    session.commit()
    logger.info(f"{fund_code} 持仓同步完成 ({len(holdings)}只股票)")


def get_fund_industry_vector(session: Session, fund_code: str):
    """计算某基金的行业分布向量"""
    from main import Stock, FundHolding  # 延迟导入

    holdings = session.exec(select(FundHolding).where(FundHolding.fund_code == fund_code)).all()
    if not holdings:
        return None

    vector = defaultdict(float)
    for h in holdings:
        stock = session.exec(select(Stock).where(Stock.code == h.stock_code)).first()
        ind = stock.industry if stock else "未分类"
        vector[ind] += h.weight
    return dict(vector)
