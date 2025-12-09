from db.database import get_session
from services.holdings import sync_fund_holdings, get_fund_industry_vector

# 手动创建一个 session
session = next(get_session())

# 你持仓的基金列表
my_funds = [
    "005827",
    "001532",
    "000083",
    "002340",
    "003096",
]  # 易方达、华安、汇添富、富国、中欧

print("🚀 开始批量同步基金持仓...\n")

for code in my_funds:
    try:
        sync_fund_holdings(session, code)
        print(f"✅ {code} 同步完成\n")
    except Exception as e:
        print(f"❌ {code} 同步失败: {e}\n")
        import traceback

        traceback.print_exc()

print("\n📊 验证行业分布（以第一个基金为例）：")
if my_funds:
    code = my_funds[0]
    vector = get_fund_industry_vector(session, code)
    if vector:
        for ind, weight in vector.items():
            print(f"   - {ind}: {weight:.2%}")
    else:
        print("   ⚠️ 暂无行业数据 (可能需要先运行 update_industries.py 补全行业信息)")
