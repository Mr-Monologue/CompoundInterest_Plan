import akshare as ak
from sqlmodel import Session, select, delete
from db.models import Stock, FundHolding
from datetime import datetime
import pandas as pd
import contextlib
import os


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


def fetch_holdings_akshare(code: str):
    """
    使用 AKShare 获取基金持仓 (最稳健方案，强制直连)
    """
    symbol = code.replace("sh", "").replace("sz", "")
    current_year = datetime.now().year

    df = None
    try:
        # 强制直连，避免 VPN 干扰国内接口
        with force_no_proxy():
            # 1. 尝试获取今年的数据
            print(f"   📡 请求 AKShare (年份: {current_year})...")
            df = ak.fund_portfolio_hold_em(symbol=symbol, date=str(current_year))

            # 2. 如果今年无数据，尝试去年
            if df is None or df.empty:
                last_year = current_year - 1
                print(f"   ⚠️ 今年无数据，尝试获取去年 ({last_year})...")
                df = ak.fund_portfolio_hold_em(symbol=symbol, date=str(last_year))

        if df is None or df.empty:
            return None, None

        # 3. 数据清洗
        # AKShare 返回该年份所有季度数据，取最新季度
        latest_quarter = sorted(df["季度"].unique(), reverse=True)[0]
        print(f"   📅 锁定报告期: {latest_quarter}")

        df_latest = df[df["季度"] == latest_quarter]

        rows = []
        for _, row in df_latest.iterrows():
            # 提取字段
            weight = float(row["占净值比例"]) / 100.0
            rows.append(
                {
                    "stock_code": str(row["股票代码"]),
                    "stock_name": str(row["股票名称"]),
                    "industry": "未分类",  # 暂时未分类，依靠 update_industries 补全
                    "weight": weight,
                }
            )

        return rows, latest_quarter

    except Exception as e:
        print(f"   ❌ AKShare 获取异常: {e}")
        return None, None


def sync_fund_holdings(session: Session, fund_code: str):
    """
    同步单只基金的持仓到数据库
    """
    print(f"🔄 同步持仓: {fund_code} ...")

    # 使用 AKShare 抓取
    holdings, report_date = fetch_holdings_akshare(fund_code)

    if not holdings:
        print(f"⚠️ {fund_code} 无持仓数据")
        return

    # 1. 删旧数据
    session.exec(delete(FundHolding).where(FundHolding.fund_code == fund_code))

    # 2. 写入新数据
    for item in holdings:
        # A. 更新股票基础信息表 (Stock)
        stock = session.exec(
            select(Stock).where(Stock.code == item["stock_code"])
        ).first()
        if not stock:
            stock = Stock(
                code=item["stock_code"],
                name=item["stock_name"],
                industry=item["industry"],
            )
            session.add(stock)

        # B. 写入持仓表
        fh = FundHolding(
            fund_code=fund_code,
            stock_code=item["stock_code"],
            stock_name=item["stock_name"],
            weight=item["weight"],
            report_date=report_date,
        )
        session.add(fh)

    session.commit()
    print(f"✅ {fund_code} 同步完成 ({len(holdings)}只股票)")


from collections import defaultdict


def get_fund_industry_vector(session: Session, fund_code: str):
    """
    计算某基金的行业分布向量
    """
    holdings = session.exec(
        select(FundHolding).where(FundHolding.fund_code == fund_code)
    ).all()

    if not holdings:
        return None

    vector = defaultdict(float)
    total_weight = 0.0

    for h in holdings:
        stock = session.exec(select(Stock).where(Stock.code == h.stock_code)).first()
        ind = stock.industry if stock else "未分类"
        vector[ind] += h.weight
        total_weight += h.weight

    return dict(vector)
