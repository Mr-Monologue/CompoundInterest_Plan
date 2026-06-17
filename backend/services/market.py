import requests
import pandas as pd
import yfinance as yf
from datetime import datetime
import time
import os
import contextlib
import random

# === 全局缓存 ===
_market_cache = {}
CACHE_DURATION = 600


# === 🛡️ 强制直连工具 ===
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
# 1. 场外基金 (005827 等) - App 接口版
# ===========================


def fetch_fund_mobile_api(code: str, use_proxy: bool):
    """
    源1: 东方财富 APP 历史净值接口 (FundMNHisNetList)
    """
    url = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList"

    # 参考实际 APP 抓包参数（大小写、字段名要注意）
    params = {
        "FCODE": code,
        "pageIndex": "1",
        "pageSize": "300",
        "plat": "Android",
        "product": "EFund",
        "version": "6.3.8",
        "deviceid": "1",
        "appType": "ttjj",
    }

    headers = {
        "User-Agent": (
            "Dalvik/2.1.0 (Linux; U; Android 10; Pixel 4 Build/QD1A.190821.007)"
        ),
        "Host": "fundmobapi.eastmoney.com",
        "Referer": "https://fund.eastmoney.com",
    }

    proxies_conf = {"http": None, "https": None} if not use_proxy else None
    mode = "VPN" if use_proxy else "直连"

    try:
        if not use_proxy:
            with force_no_proxy():
                res = requests.get(
                    url,
                    params=params,
                    headers=headers,
                    proxies=proxies_conf,
                    timeout=6,
                )
        else:
            res = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=6,
            )

        res.raise_for_status()
        data = res.json()

        # 典型返回结构: {"Datas": [...], "ErrCode":0, ...}
        datas = data.get("Datas")
        if not datas:
            print(
                f"⚠️ [Eastmoney基金] {code} ({mode}) Datas 为空 "
                f"(keys={list(data.keys())})"
            )
            return None

        rows = []
        for item in datas:
            # 典型 item: {"FSRQ":"2023-11-24","DWJZ":"1.9833", ...}
            try:
                rows.append(
                    {
                        "date": item["FSRQ"],
                        "close": float(item["DWJZ"]),
                    }
                )
            except Exception as e:
                print(
                    f"⚠️ [Eastmoney基金] {code} ({mode}) 单行解析失败: {e} item={item}"
                )

        if not rows:
            print(f"⚠️ [Eastmoney基金] {code} ({mode}) rows 为空")
            return None

        rows.reverse()  # 按日期升序
        print(f"✅ [Eastmoney基金] {code} ({mode}) 拿到 {len(rows)} 条")
        return pd.DataFrame(rows)

    except Exception as e:
        print(f"❌ [Eastmoney基金] {code} ({mode}) 请求/解析失败: {e}")
        return None


def fetch_fund_tencent(code: str):
    """
    源2: 腾讯财经 (极简接口，适合备用)
    """
    url = "http://web.ifzq.gtimg.cn/fund/newfund/fundSjk/getSjk"
    params = {"symbol": f"jj{code}", "startDate": "20200101", "limit": 300}

    try:
        # 腾讯直连通常没问题
        with force_no_proxy():
            res = requests.get(
                url, params=params, proxies={"http": None, "https": None}, timeout=6
            )
            res.raise_for_status()
            data = res.json()
            if data and data.get("data"):
                k_data = data["data"].get(f"jj{code}")
                if k_data:
                    rows = []
                    for item in k_data:
                        # 腾讯日期格式: 20231124
                        d_str = str(item[0])
                        d_fmt = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:]}"
                        rows.append({"date": d_fmt, "close": float(item[1])})
                    if rows:
                        print(f"✅ [腾讯基金] {code} 拿到 {len(rows)} 条")
                        return pd.DataFrame(rows)
                    else:
                        print(f"⚠️ [腾讯基金] {code} k_data 为空")
                else:
                    print(f"⚠️ [腾讯基金] {code} 未找到 jj{code} 数据")
            else:
                print(
                    f"⚠️ [腾讯基金] {code} JSON 结构不符合预期: {list(data.keys()) if data else 'None'}"
                )
    except Exception as e:
        print(f"❌ [腾讯基金] {code} 请求/解析失败: {e}")
    return None


def fetch_mutual_fund(code: str):
    print(f"📡 [场外基金] {code} 开始获取...")

    # 1. 首选: 东财 App 接口 (直连) -> 成功率最高
    df = fetch_fund_mobile_api(code, use_proxy=False)
    if df is not None:
        return df

    # 2. 备选: 腾讯财经 (直连)
    print(f"   🔄 切腾讯源...")
    df = fetch_fund_tencent(code)
    if df is not None:
        return df

    # 3. 兜底: 东财 App 接口 (VPN)
    print(f"   🔄 切VPN通道...")
    df = fetch_fund_mobile_api(code, use_proxy=True)

    return df


# ===========================
# 2. 场内 ETF/股票 (sh000300 等) - 保持硬核直连
# ===========================
def fetch_eastmoney_etf(code: str):
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
        with force_no_proxy():
            res = requests.get(
                url, params=params, proxies={"http": None, "https": None}, timeout=5
            )
            res.raise_for_status()
            data = res.json()
            if data.get("data") and data["data"].get("klines"):
                df = _parse_etf_data(data)
                if df is not None and not df.empty:
                    print(f"✅ [Eastmoney ETF] {code} (直连) 拿到 {len(df)} 条")
                    return df
                else:
                    print(f"⚠️ [Eastmoney ETF] {code} (直连) 解析后为空")
            else:
                print(f"⚠️ [Eastmoney ETF] {code} (直连) JSON 结构不符合预期")
    except Exception as e:
        print(f"❌ [Eastmoney ETF] {code} (直连) 请求/解析失败: {e}")

    # 2. 试 VPN
    try:
        res = requests.get(url, params=params, timeout=5)
        res.raise_for_status()
        data = res.json()
        if data.get("data") and data["data"].get("klines"):
            df = _parse_etf_data(data)
            if df is not None and not df.empty:
                print(f"✅ [Eastmoney ETF] {code} (VPN) 拿到 {len(df)} 条")
                return df
            else:
                print(f"⚠️ [Eastmoney ETF] {code} (VPN) 解析后为空")
        else:
            print(f"⚠️ [Eastmoney ETF] {code} (VPN) JSON 结构不符合预期")
    except Exception as e:
        print(f"❌ [Eastmoney ETF] {code} (VPN) 请求/解析失败: {e}")

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
    # 仅作为最后的备选
    raw_code = code.replace("sh", "").replace("sz", "")
    y_code = f"{raw_code}.SS" if "sh" in code else f"{raw_code}.SZ"
    try:
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
            print(f"✅ [Yahoo] {code} 拿到 {len(df)} 条")
            return df
        else:
            print(f"⚠️ [Yahoo] {code} 返回数据为空")
    except Exception as e:
        print(f"❌ [Yahoo] {code} 请求/解析失败: {e}")
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
        print(f"❌ 无法获取 {code} ({name}) 的历史数据")
        return {
            "fund_code": code,
            "name": name,
            "action": "ERROR",
            "reason": "数据源连接失败",
            "history": [],
        }

    try:
        import numpy as np

        df.columns = [str(c).lower() for c in df.columns]

        # 兼容性重命名
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
        print(f"❌ 计算异常: {e}")
        return {"fund_code": code, "action": "ERROR", "reason": str(e)}


# ── Auto-detect fund ────────────────────────────────

_PROXY_KW = {
    "消费": "000932", "食品": "000932", "白酒": "399997",
    "医药": "000991", "医疗": "000991",
    "科技": "399006", "信息": "399006",
    "金融": "000016", "银行": "000016",
    "新能源": "000941", "军工": "399967",
    "文体": "000300", "价值": "000300", "混合": "000300",
}


def auto_detect_fund(code: str) -> dict:
    import requests as _r
    result = {"code": code, "name": f"基金{code}", "proxy": "000300"}
    try:
        url = f"https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key={code}"
        r = _r.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        d = r.json()
        if d.get("Datas"):
            name = d["Datas"][0].get("NAME", "")
            result["name"] = name
            for kw, px in _PROXY_KW.items():
                if kw in name:
                    result["proxy"] = px; break
    except Exception:
        pass
    return result


# ── Risk guard ──────────────────────────────────────

def risk_guard(nav=None, ma200=None, dev_pct=None, source=""):
    errors = []
    if source and source.lower() == "mock":
        errors.append("Mock data")
    if nav is not None and (nav <= 0 or nav > 20):
        errors.append(f"NAV anomaly: {nav}")
    if ma200 is not None and ma200 <= 0:
        errors.append(f"MA200 anomaly: {ma200}")
    if dev_pct is not None and abs(dev_pct) > 0.5:
        errors.append(f"dev_pct anomaly: {dev_pct*100:.2f}%")
    return len(errors) == 0, errors
