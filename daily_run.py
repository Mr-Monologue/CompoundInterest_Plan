# daily_run.py
import logging
import akshare as ak
import yfinance as yf
from datetime import date, datetime, timedelta
import random, time
import pandas as pd
from storage import connect_db, init_db
from data_sources import get_index_data_with_fallback, get_latest_nav_with_fallback
from signals import calculate_ma200_deviation, calculate_dca_allocation
from holdings import HoldingsCalculator
from config import load_config

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


YF_TICKER = "000932.SS"  # 修正为 .SS（上交所）。不要用 .SZ


def _yf_download_retry(
    ticker=YF_TICKER, period="1y", interval="1d", max_retries=4, base_sleep=2.0
):
    """
    yfinance 限流友好下载：指数退避 + 抖动 + 显式 auto_adjust
    """
    for i in range(max_retries):
        try:
            df = yf.download(
                ticker,
                period=period,
                interval=interval,
                progress=False,
                threads=False,
                auto_adjust=False,  # 显式设定，消除 FutureWarning
                group_by="ticker",
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:
            # 常见: YFRateLimitError('Too Many Requests...')
            # 指数退避 + 抖动，避免“雪崩式重试”
            sleep = base_sleep * (2**i) + random.uniform(0, 0.8)
            print(f"[YF] attempt {i+1} failed: {e} → sleep {sleep:.1f}s")
            time.sleep(sleep)
    return None


def get_index_data_direct():
    """
    优先 yfinance(000932.SS) → 回退 AKShare → 兜底：东财/Mock
    """
    # 1) yfinance
    df = _yf_download_retry(YF_TICKER, period="1y", interval="1d")
    if df is not None:
        df = df.rename(columns={"Close": "close"})
        df["date"] = pd.to_datetime(df.index)
        df["ma200"] = df["close"].rolling(200).mean()
        return df[["date", "close", "ma200"]], "yfinance", None

    # 2) AKShare （指数日线）
    try:
        # 优先新版指数接口；若变更，可回退到其他指数接口
        df2 = ak.stock_zh_index_daily_em(symbol="000932")
        if df2 is not None and not df2.empty:
            df2 = (
                df2.rename(columns={"日期": "date", "收盘": "close"})
                if "日期" in df2.columns
                else df2
            )
            # 有的版本列名是英文：date, open, close, high, low, volume
            if "date" not in df2.columns:
                df2.columns = ["date", "open", "close", "high", "low", "volume"]
            df2["date"] = pd.to_datetime(df2["date"])
            df2["ma200"] = df2["close"].rolling(200).mean()
            df2 = df2.sort_values("date")
            return df2[["date", "close", "ma200"]], "AKShare", None
    except Exception as e:
        print(f"[AKShare] index fallback failed: {e}  （升级 AKShare 可修复部分接口）")

    # 3) 兜底：Mock（或你可加东财/新浪的解析）
    end_date = datetime.now()
    start_date = end_date - timedelta(days=300)
    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    prices = [15000 + i * 0.5 for i in range(len(dates))]
    mock = pd.DataFrame({"date": dates, "close": prices})
    mock["ma200"] = mock["close"].rolling(200).mean()
    return mock, "Mock", "All data sources failed"


def _akshare_nav_retry(fund_code, max_retries=3, base_sleep=1.5):
    """
    AKShare 限流友好下载：指数退避 + 抖动
    """
    for i in range(max_retries):
        try:
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            if df is not None and not df.empty and "单位净值" in df.columns:
                df = df.copy()
                df["净值日期"] = pd.to_datetime(df["净值日期"])
                df.sort_values("净值日期", inplace=True)
                nav = float(df["单位净值"].iloc[-1])
                return nav, "AKShare", None
        except Exception as e:
            sleep = base_sleep * (2**i) + random.uniform(0, 0.5)
            print(f"[AKShare NAV] attempt {i+1} failed: {e} → sleep {sleep:.1f}s")
            time.sleep(sleep)
    return None, "Failed", "All attempts failed"


def get_latest_nav_direct(fund_code, fund_name_en):
    """
    获取基金最新净值：优先 AKShare → 回退 yfinance
    """
    # 1) AKShare
    nav, src, err = _akshare_nav_retry(fund_code)
    if nav is not None:
        return nav, src, err

    # 2) yfinance (less preferred due to rate limiting)
    try:
        ticker = f"{fund_code}.SZ"
        df2 = _yf_download_retry(ticker, period="5d", interval="1d")
        if df2 is not None and not df2.empty:
            latest_close = df2["Close"].iloc[-1]
            return latest_close, "yfinance", None
    except Exception as e:
        print(f"[YF NAV] failed: {e}")

    return None, "Failed", "All attempts failed"


def main():
    logger.info(f"AKShare 版本: {ak.__version__}")
    config = load_config()
    init_db()
    nav, nav_src, err = get_latest_nav_direct(
        config["fund_code"], config["fund_name_en"]
    )
    if nav is None:
        logger.error("无法获取净值数据。请检查网络连接或稍后再试。")
        return

    # 2) 指数代理 + MA200 & 偏离
    today = date.today().isoformat()
    with connect_db() as con:
        row = pd.read_sql(
            "SELECT * FROM proxy_daily WHERE date = ?", con, params=[today]
        )
    if not row.empty:
        # 直接复用今日数据，避免再次请求
        df_proxy = pd.DataFrame(
            {
                "date": [pd.to_datetime(row.loc[0, "date"])],
                "close": [row.loc[0, "close"]],
                "ma200": [row.loc[0, "ma200"]],
            }
        )
        used_src = row.loc[0, "source"]
    else:
        df_proxy, used_src, _ = get_index_data_direct()
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
    try:
        with connect_db() as con:
            con.execute(
                "INSERT OR REPLACE INTO nav_daily(date, nav, source, timestamp) VALUES (?,?,?,?)",
                (today, float(nav), nav_src, int(datetime.now().timestamp())),
            )
            con.execute(
                """INSERT OR REPLACE INTO proxy_daily(date, close, ma200, dev_pct, source, timestamp)
                           VALUES (?,?,?,?,?,?)""",
                (
                    today,
                    float(last_row["close"]),
                    float(last_row["ma200"]),
                    float(dev),
                    used_src,
                    int(datetime.now().timestamp()),
                ),
            )
            con.execute(
                """INSERT OR REPLACE INTO dca_plan
                           (date, level, dev_pct, base_amt, dyn_amt, total_amt, reserve_before, reserve_after, timestamp)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    today,
                    plan["level"],
                    plan["deviation_pct"],
                    plan["fixed_amount"],
                    plan["dynamic_amount"],
                    plan["total_amount"],
                    plan["reserve_before"],
                    plan["reserve_after"],
                    int(datetime.now().timestamp()),
                ),
            )
            con.execute(
                """INSERT OR REPLACE INTO holdings_snapshot
                           (date, units, avg_cost, nav, mtm, unreal_pnl, unreal_pct, total_pnl, timestamp)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    today,
                    hold["units"],
                    hold["avg_cost"],
                    hold["current_nav"],
                    hold["market_value"],
                    hold["unrealized_pnl"],
                    hold["unrealized_pct"],
                    hold["total_pnl"],
                    int(datetime.now().timestamp()),
                ),
            )
    except Exception as e:
        logger.error(f"入库失败: {e}")
        con.rollback()
    # 6) 终端摘要输出（跑完就能看见）
    logger.info("=== daily_run 成功 ===")
    logger.info(f"日期: {today}")
    logger.info(f"净值: {nav:.4f} | 来源: {nav_src}")
    logger.info(
        f"指数源: {used_src} | 收盘: {float(last_row['close']):.2f} | MA200: {float(last_row['ma200']):.2f} | 偏离: {float(dev):.2f}%"
    )
    logger.info(
        f"[定投计划] 分层: {plan['level']} | 固定: {plan['fixed_amount']:.2f} | 动态: {plan['dynamic_amount']:.2f} | 合计: {plan['total_amount']:.2f}"
    )
    logger.info(
        f"[持仓快照] 份额: {hold['units']:.4f} | 成本: {hold['avg_cost']:.4f} | 当前净值: {hold['current_nav']:.4f} | 市值: {hold['market_value']:.2f} | 持有盈亏: {hold['unrealized_pnl']:.2f} ({hold['unrealized_pct']:.2f}%) | 累计盈亏: {hold['total_pnl']:.2f}"
    )


if __name__ == "__main__":
    main()
