"""auto_detect.py — Auto-detect fund name and proxy from fund code.

Category → proxy mapping (A-share index proxy):
    消费/食品/白酒 → 000932 (中证消费)
    医药/医疗 → 000991 (全指医药)
    科技/TMT → 399006 (创业板指)
    金融/银行 → 000016 (上证50)
    新能源 → 000941 (新能源)
    其余 → 000300 (沪深300, default)
"""

PROXY_MAP = {
    "消费": ("000932", "000932.SS"),
    "食品": ("000932", "000932.SS"),
    "白酒": ("399997", "399997.SZ"),
    "饮料": ("000932", "000932.SS"),
    "医药": ("000991", "000991.SS"),
    "医疗": ("000991", "000991.SS"),
    "文体": ("000300", "000300.SS"),
    "科技": ("399006", "399006.SZ"),
    "信息": ("399006", "399006.SZ"),
    "电子": ("399006", "399006.SZ"),
    "金融": ("000016", "000016.SS"),
    "银行": ("000016", "000016.SS"),
    "证券": ("399975", "399975.SZ"),
    "券商": ("399975", "399975.SZ"),
    "新能源": ("000941", "000941.SS"),
    "军工": ("399967", "399967.SZ"),
    "制造": ("000300", "000300.SS"),
    "价值": ("000300", "000300.SS"),
    "蓝筹": ("000300", "000300.SS"),
    "混合": ("000300", "000300.SS"),
    "精选": ("000300", "000300.SS"),
    "中小盘": ("000905", "000905.SS"),
}

DEFAULT_PROXY = ("000300", "000300.SS")


def detect_proxy(fund_name: str) -> tuple:
    """Match fund name keywords to proxy index. Returns (proxy_code, proxy_en)."""
    for keyword, proxy in PROXY_MAP.items():
        if keyword in fund_name:
            return proxy
    return DEFAULT_PROXY


def auto_detect_fund(fund_code: str) -> dict:
    """Try to get fund info from network, fall back to default proxy.

    Returns: {fund_code, fund_name, fund_name_en, proxy_index, proxy_index_en}
    """
    import urllib.request, json, re

    result = {
        "fund_code": fund_code,
        "fund_name": "",
        "fund_name_en": f"{fund_code}.SZ",
        "proxy_index": DEFAULT_PROXY[0],
        "proxy_index_en": DEFAULT_PROXY[1],
    }

    # Try online lookup
    try:
        url = f"https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx?m=1&key={fund_code}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data.get("Datas"):
                name = data["Datas"][0].get("NAME", "")
                code_full = data["Datas"][0].get("CODE", fund_code)
                result["fund_name"] = name
                result["fund_name_en"] = f"{code_full}.SZ" if "." not in code_full else code_full
                proxy_i, proxy_e = detect_proxy(name)
                result["proxy_index"] = proxy_i
                result["proxy_index_en"] = proxy_e
    except Exception:
        # Network failed — use code-based fallback
        result["fund_name"] = f"基金{fund_code}"
        result["fund_name_en"] = f"{fund_code}.SZ"

    return result
