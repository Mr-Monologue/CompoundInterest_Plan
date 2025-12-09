# test_akshare_holdings.py

import akshare as ak
import pandas as pd


def fetch_fund_holdings_cninfo(fund_code: str):
    """
    尝试用 AKShare 的 CNINFO 接口获取基金重仓／持仓数据。
    返回 DataFrame，或 None（如果没数据 / 接口不存在 / 出错）
    """
    try:
        df = ak.fund_report_stock_cninfo(symbol=fund_code)
    except Exception as e:
        print(f"❌ AKShare 请求失败 for {fund_code}: {e}")
        return None

    if df is None or df.empty:
        print(f"⚠️ AKShare 对 {fund_code} 未返回持仓数据（空 DataFrame）")
        return None

    return df


if __name__ == "__main__":
    fund_codes = ["005827", "000083", "003096", "001532"]
    for code in fund_codes:
        print("=== Fund", code, "===")
        df = fetch_fund_holdings_cninfo(code)
        if df is not None:
            print(df.head(10))
            print(f"✅ 共 {len(df)} 条重仓记录")
        print()
