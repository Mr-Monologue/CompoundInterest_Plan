"""v1.0.2 Holding Snapshot Pipeline — populate fund_holding_snapshot from various sources."""
import json, os
from datetime import datetime, date
from sqlmodel import Session, select
from db.models import FundHoldingSnapshot, Asset

def generate_snapshot_from_local(fund_code: str, fund_name: str, session: Session) -> dict:
    """Generate a holding snapshot from local heuristics when AKShare is unavailable."""
    data = _local_fund_holdings(fund_code, fund_name)
    now = datetime.now().isoformat()
    period = f"{datetime.now().year}Q{(datetime.now().month-1)//3+1}"

    existing = session.exec(select(FundHoldingSnapshot).where(
        FundHoldingSnapshot.fund_code == fund_code,
        FundHoldingSnapshot.report_period == period
    )).first()

    if existing:
        existing.top10_json = json.dumps(data["top10"], ensure_ascii=False)
        existing.industry_distribution_json = json.dumps(data["industry"], ensure_ascii=False)
        existing.updated_at = datetime.now()
        existing.source = data["source"]
    else:
        s = FundHoldingSnapshot(fund_code=fund_code, report_period=period, holding_date=now,
                                source=data["source"], top10_json=json.dumps(data["top10"], ensure_ascii=False),
                                industry_distribution_json=json.dumps(data["industry"], ensure_ascii=False))
        session.add(s)
    session.commit()

    return {
        "fund_code": fund_code, "report_period": period,
        "top10": data["top10"], "industry": data["industry"],
        "source": data["source"], "source_name": data.get("source_name", data["source"]),
        "is_fixture": data.get("is_fixture", True), "is_fallback": data.get("is_fallback", True),
        "snapshot_status": "OK" if data.get("top10") else "SNAPSHOT_EMPTY",
        "usable_for_live_decision": False,
        "stale_days": 0, "fetched_at": now, "top10_count": len(data["top10"]),
        "industry_count": len(data["industry"]),
    }


def run_pipeline_for_all(session: Session) -> dict:
    """Generate snapshots for all funds."""
    assets = session.exec(select(Asset)).all()
    results = {}
    for a in assets:
        try:
            r = generate_snapshot_from_local(a.code, a.name, session)
            results[a.code] = r.get("source", "error")
        except Exception as e:
            results[a.code] = f"error: {e}"
    return {"ok": True, "results": results}


def _local_fund_holdings(fund_code: str, fund_name: str) -> dict:
    """Local heuristics for fund holdings when live data unavailable.
    In production, replace with AKShare/eastmoney API calls."""
    base = {"source": "local_heuristic", "source_name": "本地规则推断（非真实披露）", "is_fixture": True, "is_fallback": True}
    holdings = {
        "000083": {"top10": [{"name":"贵州茅台","pct":9.8},{"name":"五粮液","pct":8.5},{"name":"泸州老窖","pct":6.2},{"name":"伊利股份","pct":5.1},{"name":"海天味业","pct":4.3},{"name":"美的集团","pct":3.9},{"name":"格力电器","pct":3.5},{"name":"比亚迪","pct":3.1},{"name":"牧原股份","pct":2.8},{"name":"双汇发展","pct":2.4}], "industry":{"食品饮料":35,"家电":18,"汽车":10,"农业":8,"医药":5,"其他":24}},
        "001532": {"top10": [{"name":"贵州茅台","pct":7.2},{"name":"五粮液","pct":6.1},{"name":"宁德时代","pct":5.5},{"name":"美的集团","pct":4.8},{"name":"中国平安","pct":4.2},{"name":"招商银行","pct":3.9},{"name":"腾讯控股","pct":3.5},{"name":"药明康德","pct":3.2},{"name":"隆基绿能","pct":2.9},{"name":"比亚迪","pct":2.5}], "industry":{"消费":25,"科技":22,"金融":18,"新能源":12,"医药":8,"其他":15}},
        "002340": {"top10": [{"name":"中国平安","pct":8.5},{"name":"招商银行","pct":7.8},{"name":"万科A","pct":6.2},{"name":"美的集团","pct":5.5},{"name":"格力电器","pct":4.9},{"name":"海螺水泥","pct":4.3},{"name":"伊利股份","pct":3.8},{"name":"中国建筑","pct":3.5},{"name":"保利发展","pct":3.1},{"name":"中国中铁","pct":2.8}], "industry":{"金融":25,"地产":18,"消费":15,"制造":12,"建筑":10,"其他":20}},
        "003096": {"top10": [{"name":"迈瑞医疗","pct":9.5},{"name":"恒瑞医药","pct":8.8},{"name":"药明康德","pct":7.2},{"name":"爱尔眼科","pct":6.1},{"name":"泰格医药","pct":5.3},{"name":"长春高新","pct":4.8},{"name":"片仔癀","pct":4.2},{"name":"智飞生物","pct":3.9},{"name":"云南白药","pct":3.5},{"name":"华兰生物","pct":3.1}], "industry":{"医药":65,"生物科技":20,"其他":15}},
        "005827": {"top10": [{"name":"贵州茅台","pct":9.2},{"name":"五粮液","pct":7.8},{"name":"腾讯控股","pct":6.5},{"name":"美的集团","pct":5.1},{"name":"香港交易所","pct":4.8},{"name":"招商银行","pct":4.2},{"name":"中国平安","pct":3.9},{"name":"海天味业","pct":3.5},{"name":"药明康德","pct":3.1},{"name":"宁德时代","pct":2.8}], "industry":{"消费":30,"金融":22,"科技":18,"医药":10,"新能源":8,"其他":12}},
        "000032": {"top10": [{"name":"国债2301","pct":15},{"name":"国开债2302","pct":12},{"name":"农发债2301","pct":10},{"name":"中期票据","pct":8},{"name":"企业债AAA","pct":7},{"name":"商业银行债","pct":6},{"name":"短融AAA","pct":5},{"name":"可转债","pct":4},{"name":"ABS优先级","pct":3},{"name":"货币基金","pct":2}], "industry":{"国债":30,"金融债":25,"信用债":20,"其他":25}},
    }
    fund_data = holdings.get(fund_code, {"top10": [], "industry": {}})
    return {**base, "top10": fund_data.get("top10", []), "industry": fund_data.get("industry", {})}
