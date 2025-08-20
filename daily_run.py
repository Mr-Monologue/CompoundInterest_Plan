# daily_run.py
from datetime import date, datetime, timedelta
import pandas as pd
from storage import connect_db, init_db
import akshare as ak
import yfinance as yf
from data_sources import get_index_data_with_fallback, get_latest_nav_with_fallback
from signals import calculate_ma200_deviation, calculate_dca_allocation
from holdings import HoldingsCalculator
from config import load_config
import time


def get_latest_nav_direct(fund_code, fund_code_en, retries=3):
    for attempt in range(retries):
        try:
            # AKShare
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            if df is not None and not df.empty and "单位净值" in df.columns:
                df = df.copy()
                df["净值日期"] = pd.to_datetime(df["净值日期"])
                df.sort_values("净值日期", inplace=True)
                nav = float(df["单位净值"].iloc[-1])
                return nav, "AKShare", None
        except Exception as e:
            print(f"AKShare attempt {attempt+1} failed: {e}")
            time.sleep(2**attempt)

        try:
            # yfinance
            ticker = yf.Ticker(fund_code_en)
            hist = ticker.history(period="5d")
            if not hist.empty:
                nav = float(hist["Close"].iloc[-1])
                return nav, "yfinance", None
        except Exception as e:
            print(f"yfinance attempt {attempt+1} failed: {e}")
            time.sleep(2**attempt)

    return None, "Failed", "All attempts failed"


def get_index_data_direct(index_code, symbol, period="1y"):
    try:
        df = yf.download(symbol, period=period, progress=False)
        if not df.empty:
            df = df.rename(columns={"Close": "close"})
            df["date"] = pd.to_datetime(df.index)
            df["ma200"] = df["close"].rolling(window=200).mean()
            return df[["date", "close", "ma200"]], "yfinance", None
    except:
        pass
    try:
        df = ak.stock_zh_index_daily_em(symbol=index_code)
        if not df.empty:
            df.columns = ["date", "open", "close", "high", "low", "volume"]
            df["date"] = pd.to_datetime(df["date"])
            df["ma200"] = df["close"].rolling(window=200).mean()
            return df[["date", "close", "ma200"]], "AKShare", None
    except:
        pass
    # Generate mock data as fallback
    end_date = datetime.now()
    start_date = end_date - timedelta(days=300)
    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    prices = [1000 + i * 0.5 for i in range(len(dates))]  # Simple mock
    df = pd.DataFrame({"date": dates, "close": prices})
    df["ma200"] = df["close"].rolling(window=200).mean()
    return df, "Mock", None


def main():
    init_db()
    today = date.today().isoformat()
    config = load_config()

    # 1) 净值
    nav, nav_src, err = get_latest_nav_direct(
        config["fund_code"], config["fund_name_en"]
    )
    if nav is None:
        print(f"净值获取失败: {err}. Using default nav=0.0")
        nav = 0.0

    # 2) 指数代理 + MA200 & 偏离
    df_proxy, used_src, _ = get_index_data_direct(
        config["proxy_index"], f"{config['proxy_index']}.SZ"
    )
    deviation_info = calculate_ma200_deviation(df_proxy, nav)
    dev = deviation_info["deviation_pct"]
    last_row = df_proxy.iloc[-1]

    # 3) 动态定投建议
    state = {}  # TODO: Load actual state if needed
    plan = calculate_dca_allocation(config, state, deviation_info)

    # 4) 当前持仓快照
    holdings_calculator = HoldingsCalculator(config)
    if nav == 0.0:
        hold = {
            "units": 0,
            "avg_cost": 0,
            "current_nav": 0,
            "market_value": 0,
            "unrealized_pnl": 0,
            "unrealized_pct": 0,
            "total_pnl": 0,
        }
    else:
        hold = holdings_calculator.calculate_holdings_summary(nav)

    # 5) 入库
    with connect_db() as con:
        con.execute(
            "INSERT OR REPLACE INTO nav_daily(date, nav, source) VALUES (?,?,?)",
            (today, float(nav), nav_src),
        )
        con.execute(
            """INSERT OR REPLACE INTO proxy_daily(date, close, ma200, dev_pct, source)
                       VALUES (?,?,?,?,?)""",
            (
                today,
                float(last_row["close"]),
                float(last_row["ma200"]),
                float(dev),
                used_src,
            ),
        )
        con.execute(
            """INSERT OR REPLACE INTO dca_plan
                       (date, level, dev_pct, base_amt, dyn_amt, total_amt, reserve_before, reserve_after)
                       VALUES (?,?,?,?,?,?,?,?)""",
            (
                today,
                plan["level"],
                plan["deviation_pct"],
                plan["fixed_amount"],
                plan["dynamic_amount"],
                plan["total_amount"],
                plan["reserve_before"],
                plan["reserve_after"],
            ),
        )
        con.execute(
            """INSERT OR REPLACE INTO holdings_snapshot
                       (date, units, avg_cost, nav, mtm, unreal_pnl, unreal_pct, total_pnl)
                       VALUES (?,?,?,?,?,?,?,?)""",
            (
                today,
                hold["units"],
                hold["avg_cost"],
                hold["current_nav"],
                hold["market_value"],
                hold["unrealized_pnl"],
                hold["unrealized_pct"],
                hold["total_pnl"],
            ),
        )


if __name__ == "__main__":
    main()
