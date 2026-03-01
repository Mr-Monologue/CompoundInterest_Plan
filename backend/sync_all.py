from sqlmodel import select, Session

from db.database import engine

from db.models import Asset

from services.holdings import sync_fund_holdings

from update_industries import update_stock_industries


def sync_all_assets():
    print("🚀 开始全量同步...")

    # 1. 从数据库获取所有已添加的资产
    with Session(engine) as session:
        assets = session.exec(select(Asset)).all()
        print(f"📋 发现已关注资产: {len(assets)} 个")

        # 2. 逐个同步持仓
        for asset in assets:
            print(f"\n🔄 正在同步: {asset.name} ({asset.code})")
            try:
                sync_fund_holdings(session, asset.code)
            except Exception as e:
                print(f"   ❌ 失败: {e}")

    # 3. 同步完所有持仓后，统一补全行业信息
    print("\n📦 正在补全行业数据...")
    update_stock_industries()

    print("\n✅ === 全量同步完成 ===")


if __name__ == "__main__":
    sync_all_assets()
