#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源管理模块
- AKShare/yfinance/天天基金数据抓取与清洗
- @st.cache_data 缓存机制
- 网络失败回退策略
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
import time
import random
from ..db.storage import connect_db

# 尝试导入 requests_cache，如果失败则跳过缓存
try:
    import requests_cache

    requests_cache.install_cache("yfinance_cache", backend="sqlite", expire_after=86400)
    REQUESTS_CACHE_AVAILABLE = True
except Exception:
    requests_cache = None
    REQUESTS_CACHE_AVAILABLE = False
    print("⚠ requests_cache未安装，将跳过HTTP缓存")

# 尝试导入数据源库
try:
    import akshare as ak

    AKSHARE_AVAILABLE = True
except ImportError:
    ak = None
    AKSHARE_AVAILABLE = False
    print("⚠ AKShare未安装，将使用备用数据源")

try:
    import yfinance as yf

    YFINANCE_AVAILABLE = True
except ImportError:
    yf = None
    YFINANCE_AVAILABLE = False
    print("⚠ yfinance未安装，将使用备用数据源")


class DataSourceError(Exception):
    """数据源错误"""

    pass


try:
    import streamlit as st

    cache_data = st.cache_data
except Exception:

    def cache_data(**_kwargs):
        def deco(fn):
            return fn

        return deco


@cache_data(ttl=900)  # 15分钟缓存
def get_index_data_akshare(symbol: str, period: str = "1y") -> pd.DataFrame:
    """
    使用AKShare获取指数数据

    Args:
        symbol: 指数代码，如 "000932"
        period: 时间周期

    Returns:
        包含OHLCV数据的DataFrame
    """
    if not AKSHARE_AVAILABLE:
        raise DataSourceError("AKShare不可用")

    try:
        # 尝试使用stock_zh_index_daily_em作为替代
        df = ak.stock_zh_index_daily_em(symbol=symbol)

        if df.empty:
            raise DataSourceError("返回数据为空")

            # 检查并重命名列 - 尝试多种可能的列名组合
        column_mappings = [
            # 组合1: 标准中文列名
            (
                ["日期", "开盘", "收盘", "最高", "最低", "成交量"],
                ["date", "open", "close", "high", "low", "volume"],
            ),
            # 组合2: 可能的其他中文列名
            (
                ["日期", "开盘价", "收盘价", "最高价", "最低价", "成交量"],
                ["date", "open", "close", "high", "low", "volume"],
            ),
            # 组合3: 英文列名
            (
                ["date", "open", "close", "high", "low", "volume"],
                ["date", "open", "close", "high", "low", "volume"],
            ),
        ]

        success = False
        for expected_cols, new_cols in column_mappings:
            if all(col in df.columns for col in expected_cols):
                df = df[expected_cols].copy()
                df.columns = new_cols
                success = True
                break

        if not success:
            # 如果都不匹配，尝试使用前6列
            if len(df.columns) >= 6:
                df = df.iloc[:, :6].copy()
                df.columns = ["date", "open", "close", "high", "low", "volume"]
            else:
                raise DataSourceError(f"列数不足，只有{len(df.columns)}列")

        # 重命名列
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        # 计算MA200
        df["ma200"] = df["close"].rolling(window=200).mean()

        return df
    except Exception as e:
        raise DataSourceError(f"AKShare获取指数数据失败: {e}")


@cache_data(ttl=900)
def get_index_data_yfinance(symbol: str, period: str = "1y") -> pd.DataFrame:
    """
    使用yfinance获取指数数据

    Args:
        symbol: 指数代码，如 "000932.SZ"
        period: 时间周期，如 "1y", "2y", "max"

    Returns:
        包含OHLCV数据的DataFrame
    """
    if not YFINANCE_AVAILABLE:
        raise DataSourceError("yfinance不可用")

    try:
        # 验证period参数
        valid_periods = [
            "1d",
            "5d",
            "1mo",
            "3mo",
            "6mo",
            "1y",
            "2y",
            "5y",
            "10y",
            "ytd",
            "max",
        ]
        if period not in valid_periods:
            raise DataSourceError(
                f"无效的period参数: {period}，有效值: {valid_periods}"
            )

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)

        # 重命名列
        df.columns = ["open", "high", "low", "close", "volume"]
        df.index.name = "date"
        df = df.reset_index()

        # 计算MA200
        df["ma200"] = df["close"].rolling(window=200).mean()

        return df
    except Exception as e:
        raise DataSourceError(f"yfinance获取指数数据失败: {e}")


@cache_data(ttl=300)  # 5分钟缓存（净值更新较频繁）
def get_fund_nav_akshare(fund_code: str) -> Tuple[float, str, Optional[str]]:
    """
    使用AKShare获取基金净值

    Args:
        fund_code: 基金代码，如 "000083"

    Returns:
        (净值, 数据源, 错误信息)
    """
    if not AKSHARE_AVAILABLE:
        return None, "AKShare不可用", "AKShare未安装"

    try:
        # 获取基金净值信息
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")

        if df.empty:
            return None, "AKShare", "返回数据为空"

            # 确保数据按日期排序，取最新的一行
        if "净值日期" in df.columns:
            df["净值日期"] = pd.to_datetime(df["净值日期"])
            df = df.sort_values("净值日期", ascending=False).reset_index(drop=True)

        # 获取最新净值
        latest_nav = df.iloc[0]["单位净值"]
        nav_date = df.iloc[0]["净值日期"]

        return float(latest_nav), f"AKShare_{fund_code}", None

    except Exception as e:
        return None, "AKShare", str(e)


@cache_data(ttl=300)
def get_fund_nav_yfinance(fund_code: str) -> Tuple[float, str, Optional[str]]:
    """
    使用yfinance获取基金净值

    Args:
        fund_code: 基金代码，如 "000083.SZ"

    Returns:
        (净值, 数据源, 错误信息)
    """
    if not YFINANCE_AVAILABLE:
        return None, "yfinance不可用", "yfinance未安装"

    try:
        ticker = yf.Ticker(fund_code)
        hist = ticker.history(period="5d")

        if hist.empty:
            return None, "yfinance", "返回数据为空"

        # 获取最新收盘价作为净值
        latest_nav = hist["Close"].iloc[-1]

        return float(latest_nav), f"YF_{fund_code}", None

    except Exception as e:
        return None, "yfinance", str(e)


def get_latest_nav_with_fallback(
    fund_code: str, fund_code_en: str, manual_nav: Optional[float] = None
) -> Tuple[float, str, str]:
    """
    获取最新净值，带回退策略

    Args:
        fund_code: 基金代码（中文）
        fund_code_en: 基金代码（英文，yfinance用）
        manual_nav: 手动输入的净值

    Returns:
        (净值, 数据源, 状态信息)
    """
    # 1. 优先使用手动输入
    if manual_nav is not None:
        return manual_nav, "手动输入", "使用用户手动输入的净值"

    # 2. 尝试AKShare
    try:
        nav, source, error = get_fund_nav_akshare(fund_code)
        if nav is not None:
            return nav, source, "成功获取"
    except Exception as e:
        pass

    # 3. 回退到yfinance
    try:
        nav, source, error = get_fund_nav_yfinance(fund_code_en)
        if nav is not None:
            return nav, source, "回退获取成功"
    except Exception as e:
        pass

    # 4. 所有数据源都失败
    return None, "无可用数据源", "所有数据源都失败，请手动输入净值"


def get_index_data_with_fallback(
    symbol: str, symbol_en: str, period: str = "1y"
) -> Tuple[pd.DataFrame, str, str]:
    """
    获取指数数据，带回退策略

    Args:
        symbol: 指数代码（中文）
        symbol_en: 指数代码（英文）
        period: 时间周期

    Returns:
        (数据DataFrame, 数据源, 状态信息)
    """
    today = datetime.now().date().isoformat()
    try:
        with connect_db() as con:
            row = pd.read_sql(
                "SELECT * FROM proxy_daily_v2 WHERE fund_code=? AND date=?",
                con,
                params=[symbol, today],
            )
        if not row.empty:
            df_proxy = pd.DataFrame(
                {
                    "date": [pd.to_datetime(row.loc[0, "date"])],
                    "close": [row.loc[0, "close"]],
                    "ma200": [row.loc[0, "ma200"]],
                }
            )
            return df_proxy, row.loc[0, "source"], None
    except Exception:
        pass
    return get_index_data_direct(symbol, symbol_en)


def get_data_source_status() -> Dict[str, bool]:
    """获取各数据源的可用状态"""
    return {
        "akshare": AKSHARE_AVAILABLE,
        "yfinance": YFINANCE_AVAILABLE,
        "ttfund": False,  # 暂时未实现
    }


def generate_mock_index_data() -> pd.DataFrame:
    """生成模拟指数数据作为fallback"""
    import numpy as np
    from datetime import datetime, timedelta

    # 生成过去300天的数据
    end_date = datetime.now()
    start_date = end_date - timedelta(days=300)

    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    np.random.seed(42)  # 固定随机种子，确保结果一致

    # 模拟价格走势
    base_price = 1000
    returns = np.random.normal(0, 0.02, len(dates))  # 2%的日波动率
    prices = [base_price]

    for ret in returns[1:]:
        prices.append(prices[-1] * (1 + ret))

    # 创建DataFrame
    df = pd.DataFrame(
        {
            "date": dates,
            "open": prices,
            "high": [p * (1 + abs(np.random.normal(0, 0.01))) for p in prices],
            "low": [p * (1 - abs(np.random.normal(0, 0.01))) for p in prices],
            "close": prices,
            "volume": np.random.randint(1000000, 10000000, len(dates)),
        }
    )

    # 计算MA200
    df["ma200"] = df["close"].rolling(window=200).mean()

    return df


def clear_cache():
    """清除所有缓存"""
    st.cache_data.clear()


def get_index_data_direct(index_code, symbol):
    # 1) yfinance
    df = _yf_download_retry(symbol, period="1y", interval="1d")
    if df is not None:
        df = df.rename(columns={"Close": "close"})
        df["date"] = pd.to_datetime(df.index)
        df["ma200"] = df["close"].rolling(200).mean()
        return df[["date", "close", "ma200"]], "yfinance", None

    # 2) AKShare （指数日线）
    try:
        df2 = ak.stock_zh_index_daily_em(symbol=index_code)
        if df2 is not None and not df2.empty:
            df2 = (
                df2.rename(columns={"日期": "date", "收盘": "close"})
                if "日期" in df2.columns
                else df2
            )
            if "date" not in df2.columns:
                df2.columns = ["date", "open", "close", "high", "low", "volume"]
            df2["date"] = pd.to_datetime(df2["date"])
            df2["ma200"] = df2["close"].rolling(200).mean()
            df2 = df2.sort_values("date")
            return df2[["date", "close", "ma200"]], "AKShare", None
    except Exception as e:
        print(f"[AKShare] index fallback failed: {e}  （升级 AKShare 可修复部分接口）")

    # 3) 兜底：Mock
    end_date = datetime.now()
    start_date = end_date - timedelta(days=300)
    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    prices = [15000 + i * 0.5 for i in range(len(dates))]
    mock = pd.DataFrame({"date": dates, "close": prices})
    mock["ma200"] = mock["close"].rolling(200).mean()
    return mock, "Mock", "All data sources failed"


def _yf_download_retry(
    ticker, period="1y", interval="1d", max_retries=4, base_sleep=2.0
):
    for i in range(max_retries):
        try:
            df = yf.download(
                ticker,
                period=period,
                interval=interval,
                progress=False,
                threads=False,
                auto_adjust=False,
                group_by="ticker",
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:
            sleep = base_sleep * (2**i) + random.uniform(0, 0.8)
            print(f"[YF] attempt {i+1} failed: {e} → sleep {sleep:.1f}s")
            time.sleep(sleep)
    return None


if __name__ == "__main__":
    # 测试数据源
    print("数据源状态:")
    status = get_data_source_status()
    for source, available in status.items():
        print(f"  {source}: {'✓' if available else '✗'}")

    # 测试指数数据获取
    try:
        df, source, status = get_index_data_with_fallback("000932", "000932.SZ")
        print(f"\n✓ 成功获取指数数据: {source}")
        print(f"数据行数: {len(df)}")
        print(f"最新收盘价: {df['close'].iloc[-1]:.2f}")
        print(f"MA200: {df['ma200'].iloc[-1]:.2f}")
    except Exception as e:
        print(f"\n✗ 获取指数数据失败: {e}")

    # 测试基金净值获取
    try:
        nav, source, status = get_latest_nav_with_fallback("000083", "000083.SZ")
        if nav:
            print(f"\n✓ 成功获取基金净值: {nav:.4f} ({source})")
        else:
            print(f"\n✗ 获取基金净值失败: {status}")
    except Exception as e:
        print(f"\n✗ 获取基金净值失败: {e}")
