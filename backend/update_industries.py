"""update_industries.py — 自动行业分类（板块映射 + 缓存，无硬编码）"""
import akshare as ak
from sqlmodel import Session, select
from db.database import engine
from db.models import Stock
import os, contextlib, json
from pathlib import Path

CACHE = Path("backend/db/industry_cache.json")

@contextlib.contextmanager
def force_no_proxy():
    backup = {k: os.environ.get(k) for k in ["http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY"]}
    for k in backup: os.environ[k] = ""
    os.environ["NO_PROXY"] = "*"
    try: yield
    finally:
        for k,v in backup.items():
            if v is None: os.environ.pop(k,None)
            else: os.environ[k] = v


def build_industry_map():
    """构建代码→行业的完整映射（板块接口 + 缓存）"""
    industry_map = {}

    # 1. 加载缓存
    if CACHE.exists():
        industry_map = json.loads(CACHE.read_text())
        print(f"   📦 缓存: {len(industry_map)} 条")

    # 2. 实时拉取申万行业板块成份股
    try:
        print("   📡 拉取行业板块数据...")
        with force_no_proxy():
            boards = ak.stock_board_industry_name_em()
        for _, b in boards.iterrows():
            bname = b["板块名称"]
            try:
                with force_no_proxy():
                    stocks = ak.stock_board_industry_cons_em(symbol=bname)
                for _, s in stocks.iterrows():
                    industry_map[s["代码"]] = bname
                print(f"      {bname}: {len(stocks)}只")
            except Exception:
                pass
        CACHE.write_text(json.dumps(industry_map, ensure_ascii=False))
        print(f"   ✅ 总计 {len(industry_map)} 只股票")
    except Exception as e:
        print(f"   ⚠️ 网络获取失败: {e}")

    return industry_map


def update_stock_industries():
    print("🚀 更新行业分类...")
    industry_map = build_industry_map()

    with Session(engine) as session:
        stocks = session.exec(select(Stock).where(Stock.industry == "未分类")).all()
        if not stocks:
            print("   ✨ 全部已有行业")
            return

        print(f"   🔍 {len(stocks)} 只待补全")
        updated = 0
        for s in stocks:
            new_ind = industry_map.get(s.code, "")
            if not new_ind and len(s.code) == 5:
                new_ind = "港股/海外"
            if new_ind:
                s.industry = new_ind; session.add(s); updated += 1
                print(f"      {s.code} {s.name} → {new_ind}")
            else:
                print(f"      ❌ {s.code} {s.name}")

        session.commit()
        print(f"🎉 补全 {updated} 只")


if __name__ == "__main__":
    update_stock_industries()
