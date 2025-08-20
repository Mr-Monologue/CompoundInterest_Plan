#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dynamic DCA + Holdings Report for 汇添富消费行业混合(000083)

功能升级：
- 使用 Decimal + quantize 严格控制财务精度（金额 2 位／净值 4 位）
- MA200 偏离 → 使用线性映射控制动态定投比例，避免阈值跳变
- 支持"手动持仓／手动净值"模式，用于完脱离 CSV
- 图表功能用 try/except 包裹，确保未安装 matplotlib 时仍可输出文本

MA200 日均线重要性说明（Investopedia）：
- 200日均线是技术分析中最重要和最广泛使用的移动平均线
- 它代表了过去200个交易日的平均价格，被视为长期趋势的"分水岭"
- 当价格在200日均线之上时，通常表示长期上升趋势
- 当价格跌破200日均线时，可能预示着长期趋势的转变
- 在投资组合管理中，200日均线常用于判断市场时机和资产配置
"""

import os, sys, json, time, re, requests
from datetime import date
import pandas as pd
import numpy as np
from decimal import Decimal, ROUND_HALF_UP, getcontext

# 设置内部 decimal 精度
getcontext().prec = 28
Q2 = Decimal("0.01")  # 金额精度：2位小数
Q4 = Decimal("0.0001")  # 净值精度：4位小数


def D(x):
    """转换为Decimal类型"""
    return x if isinstance(x, Decimal) else Decimal(str(x))


def quant_amt(x):
    """金额量化到2位小数"""
    return D(x).quantize(Q2, rounding=ROUND_HALF_UP)


def quant_nav(x):
    """净值量化到4位小数"""
    return D(x).quantize(Q4, rounding=ROUND_HALF_UP)


def quant_shares(x):
    """份额量化到2位小数"""
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------- Config ----------------
CFG_DEFAULT = {
    "fund_code": "000083",
    "fund_name": "汇添富消费行业混合",
    # ——你现在不想用 CSV——
    "transactions_csv": None,  # 不使用 CSV
    "use_manual_holdings": True,  # 打开手动持仓模式
    "manual_units_left": 6.63,  # 你的剩余份额
    "manual_avg_cost": 6.8627,  # 你的持仓成本价（含费）
    "manual_realized_pnl": -7.24,  # 你已实现盈亏（卖出那次）
    "manual_nav_override": None,  # 000083 最新净值（None表示自动获取）
    "default_nav_hook": "fetch_ttfund",  # 净值获取方式：fetch_ttfund > AKShare
    # 动态定投参数
    "weekly_budget": 200.0,
    "fixed_ratio": 0.40,
    "reserve_cap_months": 3,
    "max_weekly_multiple": 3.0,
    # 估值分层阈值（按 MA200 偏离）
    "ma200_low": -10.0,  # ≤ -10% → 低估
    "ma200_mid": 5.0,  # (-10%, 5%] → 合理；>5% → 偏高
    # 低/中/高估对应动用准备金比例
    "alloc_low": 0.75,
    "alloc_mid": 0.25,
    "alloc_high": 0.0,
    "reserve_sweep_days": 90,
    "log_csv": "dca_log.csv",
    "state_file": "state.json",
    # 估值/净值离线兜底
    "manual_dev_override": None,  # 如 -12.5（MA200 偏离%）
    # manual_nav_override 在上方
    # 图表输出
    "charts": {"ma200_png": "chart_ma200.png", "buypoints_png": "chart_buypoints.png"},
}

STATE_DEFAULT = {
    "reserve_balance": 0.0,
    "last_signal_date": None,
    "last_low_trigger_date": None,
}


# ---------------- I/O helpers ----------------
def load_json(path, default_obj):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return {**default_obj, **d}
        except Exception:
            pass
    return dict(default_obj)


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# ---------------- Data fetchers ----------------
def fetch_ak_index_000932(days=800, retries=2, backoff=2.0):
    try:
        import akshare as ak
    except Exception as e:
        return None, f"AKShare未安装: {e}"
    err = None
    for i in range(retries):
        try:
            start = (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y%m%d")
            end = pd.Timestamp.today().strftime("%Y%m%d")
            df = ak.index_zh_a_hist(
                symbol="000932", period="daily", start_date=start, end_date=end
            )
            if df is None or df.empty:
                err = "AKShare返回空"
            else:
                need = {"日期": "date", "收盘": "close"}
                if not set(need.keys()).issubset(df.columns):
                    err = f"列名变化: {list(df.columns)}"
                else:
                    out = df.rename(columns=need)[["date", "close"]].copy()
                    out["date"] = pd.to_datetime(out["date"])
                    out.sort_values("date", inplace=True)
                    out.reset_index(drop=True, inplace=True)
                    return out, None
        except Exception as e:
            err = str(e)
        time.sleep(backoff * (i + 1))
    return None, err or "AKShare未知错误"


def fetch_yf(symbol, period="10y", interval="1d"):
    # yfinance 的 download 支持 period=[1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max]、interval=[1d,1wk,1mo,...]
    # （使用时必须是预定义 period 取值之一）:contentReference[oaicite:1]{index=1}
    try:
        import yfinance as yf
    except Exception as e:
        return None, f"yfinance未安装: {e}"
    try:
        df = yf.download(
            symbol, period=period, interval=interval, progress=False, threads=False
        )
        if df is None or df.empty:
            return None, "yfinance空数据"
        df = df.rename(columns={"Close": "close"})
        df["date"] = pd.to_datetime(df.index)
        return df[["date", "close"]].reset_index(drop=True), None
    except Exception as e:
        return None, str(e)


def get_proxy_series():
    errs = []
    df, err = fetch_ak_index_000932()
    if df is not None:
        return df, "AK_000932", None
    errs.append(("AK_000932", err))
    df, err = fetch_yf("000932.SS")
    if df is not None:
        return df, "YF_000932.SS", None
    errs.append(("YF_000932.SS", err))
    df, err = fetch_yf("159928.SZ")
    if df is not None:
        return df, "YF_159928.SZ", None
    errs.append(("YF_159928.SZ", err))
    return None, None, errs


def compute_ma200_dev(df):
    X = df.copy()
    X["ma200"] = X["close"].rolling(200).mean()
    if X["ma200"].isna().all() or pd.isna(X["ma200"].iloc[-1]):
        return None, None, "不足200交易日，无法算MA200"
    X["dev_pct"] = (X["close"] / X["ma200"] - 1.0) * 100.0
    dev = float(X["dev_pct"].iloc[-1])
    return X, dev, None


# ---------------- NAV ----------------
# 合理性校验：避免再出现 83.0000 这类离谱数
def _sanity_check_nav(x: float) -> bool:
    return 0.1 <= x <= 20.0  # 混合/股票/指数型的单位净值通常在这个区间内


def get_nav_em_fundgz(fund_code="000083"):
    """
    天天基金 JSONP：返回最近交易日单位净值 (dwjz) 与日期 (jzrq)
    例：http://fundgz.1234567.com.cn/js/000083.js?rt=...
    """
    url = f"http://fundgz.1234567.com.cn/js/{fund_code}.js"
    try:
        r = requests.get(
            url,
            params={"rt": int(time.time() * 1000)},
            timeout=6,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        m = re.search(r"jsonpgz\\((\\{.*?\\})\\)", r.text)
        if not m:
            return None, None, "JSONP 解析失败"
        data = json.loads(m.group(1))
        nav = float(data["dwjz"])  # 单位净值
        if not _sanity_check_nav(nav):
            return None, None, f"净值异常({nav})"
        return nav, "EM_fundgz", None
    except Exception as e:
        return None, None, str(e)


def get_nav_em_lsjz(fund_code="000083"):
    """
    东方财富 F10 历史净值 JSON：取最近一条作为当前单位净值
    需要带 Referer，否则可能返回空
    """
    url = "https://api.fund.eastmoney.com/f10/lsjz"
    params = {"fundCode": fund_code, "pageIndex": "1", "pageSize": "1"}
    headers = {
        "Referer": f"https://fundf10.eastmoney.com/jjjz_{fund_code}.html",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=6)
        r.raise_for_status()
        j = r.json()
        # 常见结构：Data -> LSJZList -> [{ "DWJZ": "4.9920", ... }]
        items = (j.get("Data") or {}).get("LSJZList") or []
        if items:
            nav = float(items[0]["DWJZ"])
            if not _sanity_check_nav(nav):
                return None, None, f"净值异常({nav})"
            return nav, "EM_lsjz", None
        return None, None, "无数据"
    except Exception as e:
        return None, None, str(e)


def get_latest_nav_000083(manual=None, fund_code="000083", default_hook="fetch_ttfund"):
    """
    获取最新净值：手动 > fundgz JSONP > F10 历史净值 > AKShare
    """
    # 1) 手动覆盖
    if manual is not None:
        nav = float(manual)
        return nav, "MANUAL", None

    # 2) fundgz（首选）
    nav, src, err_a = get_nav_em_fundgz(fund_code)
    if nav is not None:
        return nav, src, None

    # 3) F10 历史净值
    nav, src, err_b = get_nav_em_lsjz(fund_code)
    if nav is not None:
        return nav, src, None

    # 4) AKShare 兜底
    try:
        import akshare as ak

        df = ak.fund_open_fund_info_em(fund=fund_code, indicator="单位净值走势")
        if df is not None and not df.empty and "单位净值" in df.columns:
            df = df.copy()
            df["净值日期"] = pd.to_datetime(df["净值日期"])
            df.sort_values("净值日期", inplace=True)
            nav = float(df["单位净值"].iloc[-1])
            if _sanity_check_nav(nav):
                return nav, "AK_fund_open_fund_info_em", None
    except Exception:
        pass

    return None, None, f"fundgz失败: {err_a}; lsjz失败: {err_b}"


# ---------------- Holdings ----------------
def load_transactions(path):
    if not path or not os.path.exists(path):
        return None, f"找不到交易表: {path}"
    df = pd.read_csv(path, encoding="utf-8-sig")
    lc = {c.lower(): c for c in df.columns}
    need = ["date", "action", "units", "price", "fee", "cash_flow"]
    for c in need:
        if c not in lc:
            return None, f"缺字段：{c}"
    df = df.rename(columns={lc[c]: c for c in need})
    df["date"] = pd.to_datetime(df["date"])
    for col in ["units", "price", "fee", "cash_flow"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df.sort_values("date").reset_index(drop=True), None


def holdings_from_transactions(df):
    buys = df[df["action"].str.upper() == "BUY"]
    sells = df[df["action"].str.upper() == "SELL"]
    total_buy_units = buys["units"].sum()
    total_out = -df[df["cash_flow"] < 0]["cash_flow"].sum()
    total_sell_units = sells["units"].sum()
    proceeds = df[df["action"].str.upper() == "SELL"]["cash_flow"].sum()
    left = total_buy_units - total_sell_units
    avg_cost = (total_out / total_buy_units) if total_buy_units > 0 else 0.0
    cost_left = avg_cost * left
    realized = proceeds - avg_cost * total_sell_units
    return {
        "units_left": left,
        "avg_cost_inc_fee": avg_cost,
        "cost_left_inc_fee": cost_left,
        "realized_pnl": realized,
    }


def get_holdings(cfg):
    """优先用手动持仓；否则回退 CSV；都没有就返回0仓位"""
    if cfg.get("use_manual_holdings"):
        units_left = float(cfg["manual_units_left"])
        avg_cost = float(cfg["manual_avg_cost"])
        realized = float(cfg.get("manual_realized_pnl", 0.0))
        return {
            "units_left": units_left,
            "avg_cost_inc_fee": avg_cost,
            "cost_left_inc_fee": units_left * avg_cost,
            "realized_pnl": realized,
        }
    df_trx, err = load_transactions(cfg.get("transactions_csv"))
    if df_trx is None:
        return {
            "units_left": 0.0,
            "avg_cost_inc_fee": 0.0,
            "cost_left_inc_fee": 0.0,
            "realized_pnl": 0.0,
        }
    return holdings_from_transactions(df_trx)


# ---------------- Strategy ----------------
def compute_holdings_precise(units_left, avg_cost, nav_now, realized_pnl):
    """
    使用Decimal精确计算持仓信息，避免浮点误差
    """
    u = quant_shares(units_left)
    c = quant_nav(avg_cost)
    n = quant_nav(nav_now)

    # 精确计算（避免浮点误差）
    exact_cost = D(units_left) * D(avg_cost)
    exact_mtm = D(units_left) * D(nav_now)
    exact_pnl = exact_mtm - exact_cost
    exact_rate = (exact_pnl / exact_cost * 100) if exact_cost != 0 else Decimal("0")

    # 显示用（量化到合适精度）
    disp_cost = quant_amt(u * c)
    disp_mtm = quant_amt(u * n)
    disp_pnl = quant_amt(disp_mtm - disp_cost)

    # 用精确值算收益率（与支付宝一致，避免四舍误差）
    platform_rate = (
        (exact_pnl / exact_cost * Decimal("100")).quantize(Q2, rounding=ROUND_HALF_UP)
        if exact_cost != 0
        else Decimal("0")
    )

    # 总盈亏（已实现 + 未实现）
    total_pnl = D(realized_pnl) + exact_pnl

    return {
        "units": u,
        "avg_cost": c,
        "nav": n,
        "m2m_disp": disp_mtm,
        "cost_disp": disp_cost,
        "pnl_disp": disp_pnl,
        "platform_rate": platform_rate,
        "exact_pnl": exact_pnl,
        "exact_rate": exact_rate.quantize(Q2, ROUND_HALF_UP),
        "total_pnl": total_pnl.quantize(Q2, ROUND_HALF_UP),
    }


def smooth_alloc_ratio(dev_pct, low_th, mid_th, alloc_low, alloc_high):
    """
    线性动态投比例：MA200偏离在阈值之间平滑映射动用额度，避免跳跃

    参数:
        dev_pct: MA200偏离百分比
        low_th: 低估阈值（如-10%）
        mid_th: 中估阈值（如5%）
        alloc_low: 低估时动用比例（如75%）
        alloc_high: 高估时动用比例（如0%）

    返回:
        平滑的动用比例，在阈值间线性插值
    """
    d = float(dev_pct)

    # 低估区间：使用最高比例
    if d <= low_th:
        return alloc_low

    # 高估区间：使用最低比例
    if d >= mid_th:
        return alloc_high

    # 中间区间：线性插值，避免跳跃
    t = (mid_th - d) / (mid_th - low_th)  # 归一化参数 [0,1]
    return alloc_high + (alloc_low - alloc_high) * t


def decide_allocation(cfg, st, dev_pct, level):
    """
    使用平滑的动态投比例计算定投建议
    """
    B = D(cfg["weekly_budget"])
    F = D(cfg["fixed_ratio"])
    base = quant_amt(B * F)
    inflow = quant_amt(B - base)
    cap = quant_amt(B * (D("1") - F) * D("4.33") * D(cfg["reserve_cap_months"]))
    new_balance = min(st["reserve_balance"] + float(inflow), float(cap))

    # 使用平滑的动态投比例
    if level == "low":
        alloc = cfg["alloc_low"]
    elif level == "mid":
        alloc = cfg["alloc_mid"]
    else:  # high
        alloc = cfg["alloc_high"]

    # 应用平滑映射（如果在中估区间）
    if level == "mid":
        alloc = smooth_alloc_ratio(
            dev_pct,
            cfg["ma200_low"],
            cfg["ma200_mid"],
            cfg["alloc_low"],
            cfg["alloc_high"],
        )

    weekly_cap = float(B * D(cfg["max_weekly_multiple"]) - base)
    dyn = quant_amt(min(new_balance * alloc, weekly_cap, new_balance))
    end_balance = quant_amt(new_balance - float(dyn))

    return {
        "base": base,
        "dynamic": dyn,
        "total": quant_amt(base + dyn),
        "reserve_before": quant_amt(new_balance),
        "reserve_after": end_balance,
        "weekly_cap": quant_amt(weekly_cap),
        "alloc_ratio": float(alloc),
        "dev_pct": round(dev_pct, 2),
        "level": level,
    }


# ---------------- Charts ----------------
def try_make_charts(df_proxy, cfg, buys_df=None):
    """
    图表功能：用 try/except 包裹，确保未安装 matplotlib 时仍可输出文本
    """
    try:
        import matplotlib.pyplot as plt  # 未安装时会抛异常 → 直接跳过
        import matplotlib.dates as mdates

        plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]  # 支持中文
        plt.rcParams["axes.unicode_minus"] = False
    except Exception as e:
        print(f"[WARN] 未安装 matplotlib，跳过画图。安装方式：pip install matplotlib")
        return

    if df_proxy is None or df_proxy.empty:
        print("[WARN] 无数据，跳过画图")
        return

    X = df_proxy.copy()
    X["ma200"] = X["close"].rolling(200).mean()

    # a) 价格 & MA200
    plt.figure(figsize=(12, 6))
    plt.plot(
        X["date"], X["close"], label="000932收盘价", linewidth=1.5, color="#1f77b4"
    )
    plt.plot(
        X["date"],
        X["ma200"],
        label="200日均线(MA200)",
        linewidth=2,
        color="#ff7f0e",
        linestyle="--",
    )

    # 添加阈值线
    latest_close = X["close"].iloc[-1]
    latest_ma200 = X["ma200"].iloc[-1]
    dev_pct = (latest_close / latest_ma200 - 1) * 100

    plt.axhline(
        y=latest_ma200,
        color="gray",
        linestyle=":",
        alpha=0.5,
        label=f"当前MA200: {latest_ma200:.2f}",
    )
    plt.title(
        f"000932 中证主要消费指数 - MA200偏离: {dev_pct:.1f}%",
        fontsize=14,
        fontweight="bold",
    )
    plt.xlabel("日期")
    plt.ylabel("指数点位")
    plt.legend(loc="best")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    try:
        plt.savefig(cfg["charts"]["ma200_png"], dpi=150, bbox_inches="tight")
        print(f"[INFO] 已保存MA200图表: {cfg['charts']['ma200_png']}")
    except Exception as e:
        print(f"[WARN] 保存MA200图表失败: {e}")
    finally:
        plt.close()

    # b) 买点散点（没有 CSV 就不会显示）
    if buys_df is not None and len(buys_df) > 0:
        plt.figure(figsize=(12, 6))
        plt.plot(
            X["date"], X["close"], label="000932收盘价", linewidth=1.5, color="#1f77b4"
        )
        plt.plot(
            X["date"],
            X["ma200"],
            label="200日均线(MA200)",
            linewidth=2,
            color="#ff7f0e",
            linestyle="--",
        )

        # 合并买点数据
        merged = pd.merge_asof(
            buys_df.sort_values("date"),
            X[["date", "close"]].sort_values("date"),
            on="date",
            direction="backward",
        )

        if not merged.empty:
            plt.scatter(
                merged["date"],
                merged["close"],
                s=60,
                marker="o",
                color="red",
                alpha=0.8,
                label="您的买入点",
            )

        plt.title("000932 指数走势与您的买入点", fontsize=14, fontweight="bold")
        plt.xlabel("日期")
        plt.ylabel("指数点位")
        plt.legend(loc="best")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()

        try:
            plt.savefig(cfg["charts"]["buypoints_png"], dpi=150, bbox_inches="tight")
            print(f"[INFO] 已保存买点图表: {cfg['charts']['buypoints_png']}")
        except Exception as e:
            print(f"[WARN] 保存买点图表失败: {e}")
        finally:
            plt.close()


# ---------------- Main ----------------
def main():
    cfg = load_json("config.json", CFG_DEFAULT)
    st = load_json(cfg["state_file"], STATE_DEFAULT)

    # 1) 估值信号
    if cfg.get("manual_dev_override") is not None:
        dev = float(cfg["manual_dev_override"])
        df_proxy = None
        used = "MANUAL_DEV"
    else:
        df_proxy, used, errs = get_proxy_series()
        if df_proxy is None:
            print("[FATAL] 指数取数失败：", errs)
            sys.exit(2)
        df_proxy, dev, err = compute_ma200_dev(df_proxy)
        if err:
            print("[FATAL]", err)
            sys.exit(3)

    level = (
        "low"
        if dev <= cfg["ma200_low"]
        else ("mid" if dev <= cfg["ma200_mid"] else "high")
    )

    # 2) 定投建议（使用平滑的动态投比例）
    plan = decide_allocation(cfg, st, dev, level)
    today = date.today().strftime("%Y-%m-%d")
    st["reserve_balance"] = float(plan["reserve_after"])
    st["last_signal_date"] = today
    if level == "low":
        st["last_low_trigger_date"] = today
    save_json(cfg["state_file"], st)

    # 3) 持仓核算（使用Decimal精确计算）
    hold = get_holdings(cfg)
    nav, nav_src, nav_err = get_latest_nav_000083(
        manual=cfg.get("manual_nav_override"),
        fund_code=cfg.get("fund_code", "000083"),
        default_hook=cfg.get("default_nav_hook", "fetch_ttfund"),
    )
    if nav is None:
        nav = float("nan")
        nav_src = "N/A"
        if nav_err:
            print(f"[WARN] 净值获取失败: {nav_err}")

    # 使用精确计算函数
    if not np.isnan(nav):
        precise_holdings = compute_holdings_precise(
            hold["units_left"], hold["avg_cost_inc_fee"], nav, hold["realized_pnl"]
        )

        # 提取精确计算结果
        units_left = float(precise_holdings["units"])
        avg_cost = float(precise_holdings["avg_cost"])
        cost_left = float(precise_holdings["cost_disp"])
        mtm_val = float(precise_holdings["m2m_disp"])
        unreal_pnl = float(precise_holdings["pnl_disp"])
        unreal_pct = float(precise_holdings["platform_rate"])
        total_pnl = float(precise_holdings["total_pnl"])
        breakeven_nav = avg_cost if units_left > 0 else float("nan")
    else:
        # 净值获取失败时的降级处理
        units_left = hold["units_left"]
        avg_cost = hold["avg_cost_inc_fee"]
        cost_left = hold["cost_left_inc_fee"]
        mtm_val = float("nan")
        unreal_pnl = float("nan")
        unreal_pct = float("nan")
        total_pnl = hold["realized_pnl"]
        breakeven_nav = avg_cost if units_left > 0 else float("nan")

    # 4) 图表（若未安装 matplotlib 会自动跳过）
    try_make_charts(
        df_proxy if isinstance(df_proxy, pd.DataFrame) else pd.DataFrame(),
        cfg,
        buys_df=None,
    )

    # 5) 输出
    print(f"=== 动态定投建议 @ {today} ===")
    print(
        f"数据源: {used} | MA200偏离: {plan['dev_pct']}% → 分层: {plan['level']} (low<={cfg['ma200_low']}% <=mid<={cfg['ma200_mid']}%)"
    )
    print(
        f"本周预算={cfg['weekly_budget']} | 固定={plan['base']} | 动态={plan['dynamic']} | 合计={plan['total']} | 预备金: {plan['reserve_before']} → {plan['reserve_after']}"
    )

    # 显示动态投比例信息
    if level == "mid":
        smooth_ratio = smooth_alloc_ratio(
            dev, cfg["ma200_low"], cfg["ma200_mid"], cfg["alloc_low"], cfg["alloc_high"]
        )
        print(f"动态投比例: {smooth_ratio:.1%} (平滑映射，避免跳跃)")
    else:
        print(f"动态投比例: {plan['alloc_ratio']:.1%}")

    print("")
    print("=== 持仓核算（Decimal精确计算，币值对齐） ===")
    print(f"剩余份额: {units_left:.4f} | 平均成本(含费): {avg_cost:.4f}")
    print(
        f"当前净值: {('NA' if np.isnan(nav) else f'{nav:.4f}')} (来源: {nav_src}) | 持仓金额: {('NA' if np.isnan(mtm_val) else f'{mtm_val:.2f}')}"
    )
    if not np.isnan(unreal_pnl):
        print(f"持有盈亏: {unreal_pnl:.2f} ({unreal_pct:.2f}%)")
    else:
        print("持有盈亏: NA")
    if not np.isnan(total_pnl):
        print(f"累计盈亏(含已实现): {total_pnl:.2f}")
    else:
        print("累计盈亏(含已实现): NA")
    print(
        f"盈亏平衡净值: {('NA' if np.isnan(breakeven_nav) else f'{breakeven_nav:.4f}')}"
    )

    # 显示图表状态
    if os.path.exists(cfg["charts"]["ma200_png"]):
        print(f"MA200图表: ✓ {cfg['charts']['ma200_png']}")
    else:
        print("MA200图表: ✗ 未生成")

    if os.path.exists(cfg["charts"]["buypoints_png"]):
        print(f"买点图表: ✓ {cfg['charts']['buypoints_png']}")
    else:
        print("买点图表: ✗ 未生成")


if __name__ == "__main__":
    main()
