import requests
import pandas as pd
import yfinance as yf
import re
import json
from datetime import datetime
import time
import os
import contextlib

# === 全局缓存 ===
_market_cache = {}
CACHE_DURATION = 600


# === 🛡️ 网络工具：强制直连 ===
@contextlib.contextmanager
def force_no_proxy():
    proxies = {}
    for key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
        if key in os.environ:
            proxies[key] = os.environ[key]
            del os.environ[key]
    try:
        yield
    finally:
        for key, value in proxies.items():
            os.environ[key] = value


# ===========================
# 1. 场外基金抓取 (天天基金) - 双通道增强版
# ===========================
def fetch_mutual_fund_core_pingzhong(code: str, use_proxy: bool):
    """
    使用东财 pingzhongdata JS 接口抓取场外基金历史净值
    返回: DataFrame(date, close)
    """
    import traceback

    url = f"https://fund.eastmoney.com/pingzhongdata/{code}.js"

    headers = {
        "Referer": f"https://fundf10.eastmoney.com/jjjz_{code}.html",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Connection": "keep-alive",
    }

    try:
        if not use_proxy:
            with force_no_proxy():
                res = requests.get(url, headers=headers, timeout=8)
        else:
            res = requests.get(url, headers=headers, timeout=8)

        res.raise_for_status()
        text = res.text

        # Data_netWorthTrend = [ {...}, {...}, ... ]
        m = re.search(r"Data_netWorthTrend\s*=\s*(\[[^\]]*\])", text)
        if not m:
            print(f"   ⚠️ [{code}] 未找到 Data_netWorthTrend 段")
            return None

        arr = json.loads(m.group(1))
        rows = []
        for item in arr:
            # x: 时间戳(ms)，y: 单位净值
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
        mode = "VPN模式" if use_proxy else "直连模式"
        print(f"   ⚠️ [{code}] pingzhongdata {mode} 请求/解析失败: {e}")
        traceback.print_exc()
        return None


def fetch_mutual_fund_core_lsjz(code: str, use_proxy: bool):
    """
    内核函数：去天天基金抓数据 (lsjz 接口)
    use_proxy=True: 使用系统代理(VPN)
    use_proxy=False: 强制直连
    """
    import traceback

    url = "https://api.fund.eastmoney.com/f10/lsjz"  # 注意这里改成 https

    params = {
        "fundCode": code,
        "pageIndex": 1,
        "pageSize": 300,
        "startDate": "",
        "endDate": "",
        # "client": "app",  # 有些示例会加这个，可以视情况打开
    }
    headers = {
        "Referer": f"https://fundf10.eastmoney.com/jjjz_{code}.html",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Host": "api.fund.eastmoney.com",
        "Connection": "keep-alive",
    }

    try:
        if not use_proxy:
            with force_no_proxy():
                res = requests.get(url, params=params, headers=headers, timeout=8)
        else:
            res = requests.get(url, params=params, headers=headers, timeout=8)

        res.raise_for_status()

        data = res.json()

        # 这里先把返回内容打出来一眼看清
        if not data or not data.get("Data"):
            print(f"   ⚠️ [{code}] 接口返回异常 Data 为空: {data}")
            return None

        if not data["Data"].get("LSJZList"):
            print(f"   ⚠️ [{code}] 无 LSJZList，完整返回: {data}")
            return None

        lsjz = data["Data"]["LSJZList"]
        rows = []
        for item in lsjz:
            try:
                rows.append({"date": item["FSRQ"], "close": float(item["DWJZ"])})
            except Exception:
                # 某些行可能是空数据，直接跳过
                continue

        if not rows:
            print(f"   ⚠️ [{code}] LSJZList 解析后为空")
            return None

        rows.reverse()
        return pd.DataFrame(rows)

    except Exception as e:
        mode = "VPN模式" if use_proxy else "直连模式"
        print(f"   ⚠️ [{code}] {mode} 请求/解析失败: {e}")
        traceback.print_exc()
        return None


def fetch_mutual_fund(code: str):
    print(f"📡 [场外基金] 正在获取: {code} ...")

    # ① pingzhongdata 直连
    df = fetch_mutual_fund_core_pingzhong(code, use_proxy=False)

    # ② pingzhongdata + VPN
    if df is None or df.empty:
        print(f"   🔄 pingzhong 直连失败，切换 VPN 通道重试...")
        df = fetch_mutual_fund_core_pingzhong(code, use_proxy=True)

    # ③ 兜底：老 lsjz 接口
    if df is None or df.empty:
        print(f"   🔁 尝试使用 lsjz 历史净值接口...")
        df = fetch_mutual_fund_core_lsjz(code, use_proxy=False)
        if df is None or df.empty:
            df = fetch_mutual_fund_core_lsjz(code, use_proxy=True)

    return df


# ===========================
# 2. 场内 ETF/股票 直连 (硬核版)
# ===========================
def fetch_eastmoney_etf(code: str):
    print(f"📡 [场内ETF] 正在获取: {code} ...")
    raw_code = code.replace("sh", "").replace("sz", "")
    if code.startswith("sh"):
        secid = f"1.{raw_code}"
    else:
        secid = f"0.{raw_code}"

    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": "300",
    }

    # 同样使用双通道策略
    # 1. 试直连
    try:
        with force_no_proxy():
            res = requests.get(url, params=params, timeout=5)
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
        rows.append({"date": arr[0], "close": float(arr[2])})
    return pd.DataFrame(rows)


# ===========================
# 3. 辅助源：Yahoo
# ===========================
def fetch_from_yahoo(code: str):
    # 仅作为最后的备选，代码略简
    raw_code = code.replace("sh", "").replace("sz", "")
    y_code = f"{raw_code}.SS" if "sh" in code else f"{raw_code}.SZ"
    try:
        df = yf.download(
            y_code,
            period="1y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            timeout=5,
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

    # === 智能路由 ===
    is_etf = "sh" in code or "sz" in code

    if is_etf:
        # 场内：东财 -> Yahoo
        df = fetch_eastmoney_etf(code)
        if df is None:
            df = fetch_from_yahoo(code)
    else:
        # 场外：天天基金
        df = fetch_mutual_fund(code)

    if df is None or df.empty:
        print(f"❌ {code} 获取失败")
        return {
            "fund_code": code,
            "name": name,
            "action": "ERROR",
            "reason": "数据源连接失败",
            "history": [],
        }

    # === 数据计算 ===
    try:
        import numpy as np

        df.columns = [str(c).lower() for c in df.columns]
        if "fsrq" in df.columns:
            df.rename(columns={"fsrq": "date", "dwjz": "close"}, inplace=True)
        if "date" not in df.columns:
            df.rename(columns={"日期": "date", "Date": "date"}, inplace=True)
        if "close" not in df.columns:
            df.rename(columns={"收盘": "close", "Close": "close"}, inplace=True)

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
        print(f"✅ {code} 获取成功 (净值: {curr})")
        return result

    except Exception as e:
        print(f"❌ 计算失败: {e}")
        import traceback

        traceback.print_exc()
        return {"fund_code": code, "action": "ERROR", "reason": str(e)}
