"""holdings.py — 基金持仓同步 + 自动行业识别"""
import time
import contextlib
import os
import requests
from sqlmodel import Session, select, delete
from db.models import Stock, FundHolding
from collections import defaultdict


@contextlib.contextmanager
def force_no_proxy():
    backup = {k: os.environ.get(k) for k in ["http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY"]}
    for k in backup: os.environ[k] = ""
    os.environ["NO_PROXY"] = "*"
    try: yield
    finally:
        for k, v in backup.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


def _fetch_industry_akshare(code: str) -> str:
    """AKShare 个股行业查询"""
    import akshare as ak
    try:
        clean = code.replace("sh","").replace("sz","")
        if not clean.isdigit() or len(clean) != 6:
            return ""  # 港股等跳过
        with force_no_proxy():
            info = ak.stock_individual_info_em(symbol=clean)
        # info is a DataFrame with 'item' and 'value' columns
        row = info[info["item"] == "行业"]
        if not row.empty:
            return str(row["value"].iloc[0])
    except Exception as e:
        pass
    return ""


def _fetch_holdings_akshare(code: str):
    """AKShare 基金持仓（用 api 包避免模块加载卡死）"""
    import akshare as ak
    symbol = code.replace("sh","").replace("sz","")
    from datetime import datetime
    year = datetime.now().year
    df = None
    try:
        with force_no_proxy():
            df = ak.fund_portfolio_hold_em(symbol=symbol, date=str(year))
            if df is None or df.empty:
                df = ak.fund_portfolio_hold_em(symbol=symbol, date=str(year-1))
        if df is None or df.empty:
            return None, None
        q = sorted(df["季度"].unique(), reverse=True)[0]
        df = df[df["季度"] == q]
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "stock_code": str(r["股票代码"]),
                "stock_name": str(r["股票名称"]),
                "weight": float(r["占净值比例"]) / 100.0,
            })
        return rows, q
    except Exception as e:
        print(f"   ⚠️ AKShare 失败: {e}")
        return None, None


def sync_fund_holdings(session: Session, fund_code: str):
    print(f"🔄 {fund_code} ...")
    holdings, report_date = _fetch_holdings_akshare(fund_code)
    if not holdings:
        print(f"   ⚠️ 无持仓数据")
        return

    session.exec(delete(FundHolding).where(FundHolding.fund_code == fund_code))

    for item in holdings:
        sc = item["stock_code"]
        stock = session.exec(select(Stock).where(Stock.code == sc)).first()

        # 自动获取行业
        industry = ""
        if not stock or stock.industry == "未分类":
            industry = _fetch_industry_akshare(sc)
            time.sleep(0.15)  # 限速
            if not industry and len(sc) == 5: industry = "港股/海外"
            if not industry: industry = "未分类"

        if stock:
            if stock.industry == "未分类" and industry and industry != "未分类":
                stock.industry = industry
                session.add(stock)
        else:
            stock = Stock(code=sc, name=item["stock_name"], industry=industry or "未分类")
            session.add(stock)

        fh = FundHolding(fund_code=fund_code, stock_code=sc, stock_name=item["stock_name"],
                         weight=item["weight"], report_date=report_date)
        session.add(fh)

    session.commit()
    count = session.exec(select(FundHolding).where(FundHolding.fund_code == fund_code)).all()
    print(f"   ✅ {len(count)} 只股票 ({report_date})")


def get_fund_industry_vector(session: Session, fund_code: str):
    h = session.exec(select(FundHolding).where(FundHolding.fund_code == fund_code)).all()
    if not h: return None
    v = defaultdict(float)
    for x in h:
        s = session.exec(select(Stock).where(Stock.code == x.stock_code)).first()
        v[s.industry if s else "未分类"] += x.weight
    return dict(v)
