import requests
import pandas as pd
import yfinance as yf
import re
from datetime import datetime
import time
import json
import random

# === 全局缓存 ===
_market_cache = {}
CACHE_DURATION = 600

# ===========================
# 1. 场外基金 (005827 等) - 混合双打版
# ===========================


def fetch_fund_pingzhong(code: str, use_proxy: bool = False):
    """
    源0: 东财 pingzhongdata JS
    输出: DataFrame(date, close)
    """
    url = f"https://fund.eastmoney.com/pingzhongdata/{code}.js"
    headers = {
        "Referer": f"https://fundf10.eastmoney.com/jjjz_{code}.html",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
    }

    proxies = {"http": None, "https": None} if not use_proxy else None

    try:
        res = requests.get(url, headers=headers, proxies=proxies, timeout=8)
        res.raise_for_status()
        text = res.text

        # Data_netWorthTrend = [...]
        m = re.search(r"Data_netWorthTrend\s*=\s*(\[[^\]]*\])", text)
        if not m:
            print(f"   ⚠️ [{code}] 未找到 Data_netWorthTrend 段")
            return None

        arr = json.loads(m.group(1))
        rows = []
        for item in arr:
            ts = item.get("x")
            y = item.get("y")
            if ts is None or y is None:
                continue
            dt = datetime.fromtimestamp(ts / 1000.0).strftime("%Y-%m-%d")
            rows.append({"date": dt, "close": float(y)})

        if not rows:
            print(f"   ⚠️ [{code}] Data_netWorthTrend 解析后为空")
            return None

        return pd.DataFrame(rows)

    except Exception as e:
        mode = "VPN" if use_proxy else "直连"
        print(f"   ⚠️ [{code}] pingzhong {mode} 失败: {e}")
        return None


def fetch_fund_eastmoney(code: str, use_proxy: bool):
    """源1: 天天基金 (支持直连/代理切换)"""
    protocol = "https"  # 升级为 HTTPS
    url = f"{protocol}://api.fund.eastmoney.com/f10/lsjz"
    params = {"fundCode": code, "pageIndex": 1, "pageSize": 300}
    headers = {
        "Referer": "http://fundf10.eastmoney.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    # 关键配置：如果不用代理，显式设为 None
    proxies_conf = {"http": None, "https": None} if not use_proxy else None

    try:
        res = requests.get(
            url, params=params, headers=headers, proxies=proxies_conf, timeout=6
        )
        data = res.json()
        if data and data.get("Data") and data["Data"].get("LSJZList"):
            rows = []
            for item in data["Data"]["LSJZList"]:
                rows.append({"date": item["FSRQ"], "close": float(item["DWJZ"])})
            if rows:
                rows.reverse()
                return pd.DataFrame(rows)
    except Exception as e:
        pass  # 失败静默，交给下一个源
    return None


def fetch_fund_tencent(code: str):
    """源2: 腾讯财经 (备用，极简接口)"""
    # 腾讯的接口通常非常稳定，适合做备胎
    # 格式: http://web.ifzq.gtimg.cn/fund/newfund/fundSjk/getSjk?symbol=jj005827
    url = "http://web.ifzq.gtimg.cn/fund/newfund/fundSjk/getSjk"
    params = {"symbol": f"jj{code}", "startDate": "20200101", "limit": 300}

    try:
        # 腾讯通常直连更快
        res = requests.get(
            url, params=params, proxies={"http": None, "https": None}, timeout=6
        )
        data = res.json()
        if data and data.get("data"):
            # 腾讯数据结构: [[date, net_val, ...], ...]
            k_data = data["data"].get(f"jj{code}")
            if k_data:
                rows = []
                for item in k_data:
                    # item[0] 是日期 20231124，需要转格式
                    d_str = str(item[0])
                    d_fmt = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:]}"
                    rows.append({"date": d_fmt, "close": float(item[1])})
                return pd.DataFrame(rows)
    except Exception as e:
        print(f"   ⚠️ 腾讯源失败: {e}")
    return None


def fetch_mutual_fund(code: str):
    print(f"📡 [场外基金] {code} 开始获取...")

    # 0. 首选: pingzhongdata 直连
    df = fetch_fund_pingzhong(code, use_proxy=False)
    if df is not None:
        return df

    # 1. 天天基金直连
    df = fetch_fund_eastmoney(code, use_proxy=False)
    if df is not None:
        return df

    print(f"   🔄 直连失败，尝试腾讯备用源...")
    df = fetch_fund_tencent(code)
    if df is not None:
        return df

    print(f"   🔄 腾讯失败，尝试 VPN 通道...")
    # 2. pingzhong + VPN
    df = fetch_fund_pingzhong(code, use_proxy=True)
    if df is not None:
        return df

    # 3. 天天基金 + VPN
    df = fetch_fund_eastmoney(code, use_proxy=True)

    return df


# ===========================
# 2. 场内 ETF/股票 (sh000300 等)
# ===========================
def fetch_eastmoney_etf(code: str):
    """东财 K线 (强制直连优先)"""
    print(f"📡 [场内ETF] {code} 开始获取...")
    raw_code = code.replace("sh", "").replace("sz", "")
    secid = f"1.{raw_code}" if code.startswith("sh") else f"0.{raw_code}"

    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1",
        "fields2": "f51,f53",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": "300",
    }

    # 1. 试直连
    try:
        res = requests.get(
            url, params=params, proxies={"http": None, "https": None}, timeout=5
        )
        data = res.json()
        if data["data"]["klines"]:
            return _parse_etf_data(data)
    except:
        pass

    # 2. 试 VPN
    try:
        res = requests.get(url, params=params, timeout=5)
        data = res.json()
        if data["data"]["klines"]:
            return _parse_etf_data(data)
    except:
        pass

    return None


def _parse_etf_data(data):
    rows = []
    for line in data["data"]["klines"]:
        arr = line.split(",")
        rows.append({"date": arr[0], "close": float(arr[1])})
    return pd.DataFrame(rows)


# ===========================
# 3. 辅助源：Yahoo
# ===========================
def fetch_from_yahoo(code: str):
    raw_code = code.replace("sh", "").replace("sz", "")
    y_code = f"{raw_code}.SS" if "sh" in code else f"{raw_code}.SZ"
    try:
        # 移除 session 参数，防止报错
        df = yf.download(
            y_code,
            period="1y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            timeout=8,
        )
        if not df.empty:
            df = df.reset_index()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [str(c).lower() for c in df.columns]
            return df
    except:
        pass
    return None


# ===========================
# 4. 核心调度
# ===========================
def get_strategy_advice(code: str, name: str = "未知标的"):
    global _market_cache
    current_time = time.time()

    if code in _market_cache:
        cached_item = _market_cache[code]
        if current_time - cached_item["timestamp"] < CACHE_DURATION:
            print(f"⚡ [缓存命中] {code}")
            return cached_item["data"]

    df = None
    is_etf = "sh" in code or "sz" in code

    if is_etf:
        df = fetch_eastmoney_etf(code)
        if df is None:
            df = fetch_from_yahoo(code)
    else:
        df = fetch_mutual_fund(code)

    if df is None or df.empty:
        # 失败时返回具体的错误类型，方便前端显示
        return {
            "fund_code": code,
            "name": name,
            "action": "ERROR",
            "reason": "所有线路均无法连接，请检查网络",
            "history": [],
        }

    try:
        import numpy as np

        df.columns = [str(c).lower() for c in df.columns]

        # 模糊匹配列名
        if "fsrq" in df.columns:
            df.rename(columns={"fsrq": "date", "dwjz": "close"}, inplace=True)
        if "date" not in df.columns:
            # 尝试 date/Date
            if "Date" in df.columns:
                df.rename(columns={"Date": "date"}, inplace=True)
        if "close" not in df.columns:
            if "Close" in df.columns:
                df.rename(columns={"Close": "close"}, inplace=True)

        df["date"] = pd.to_datetime(df["date"])
        df["close"] = pd.to_numeric(df["close"])
        df = df.sort_values(by="date")

        df["ma200"] = df["close"].rolling(window=200).mean()
        df["log_ret"] = np.log(df["close"] / df["close"].shift(1))
        df["volatility_60"] = df["log_ret"].rolling(window=60).std()

        latest = df.iloc[-1]
        curr = float(latest["close"])
        ma200 = float(latest["ma200"]) if pd.notna(latest["ma200"]) else curr
        vol_daily = (
            float(latest["volatility_60"])
            if pd.notna(latest["volatility_60"])
            else 0.015
        )

        hist = []
        for _, row in df.tail(250).iterrows():
            hist.append(
                {
                    "date": row["date"].strftime("%Y-%m-%d"),
                    "price": row["close"],
                    "ma200": row["ma200"] if pd.notna(row["ma200"]) else None,
                }
            )

        result = {
            "fund_code": code,
            "name": name,
            "current_price": round(curr, 4),
            "ma200": round(ma200, 4),
            "vol_daily": vol_daily,
            "history": hist,
            "action": "CALCULATING",
        }

        _market_cache[code] = {"data": result, "timestamp": current_time}
        print(f"✅ {code} 成功 (价格: {curr})")
        return result

    except Exception as e:
        print(f"❌ 数据解析异常: {e}")
        import traceback

        traceback.print_exc()
        return {"fund_code": code, "action": "ERROR", "reason": f"解析失败: {str(e)}"}
