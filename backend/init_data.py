import requests

API_URL = "http://127.0.0.1:8000/api/assets"

funds = [
    # 核心宽基 (40%)
    {"code": "sh000300", "name": "沪深300", "max_weight_limit": 0.4},
    {"code": "sh000905", "name": "中证500", "max_weight_limit": 0.2},
    # 卫星策略 (20%)
    {"code": "sz159915", "name": "创业板ETF", "max_weight_limit": 0.2},
    {"code": "sh588000", "name": "科创50ETF", "max_weight_limit": 0.15},
    {"code": "sh513100", "name": "纳指ETF", "max_weight_limit": 0.25},
    {"code": "sh513180", "name": "恒生科技", "max_weight_limit": 0.2},
    # 行业主题 (15%)
    {"code": "005827", "name": "易方达蓝筹", "max_weight_limit": 0.15},
    {"code": "001532", "name": "华安文体", "max_weight_limit": 0.15},
    {"code": "000083", "name": "汇添富消费", "max_weight_limit": 0.15},
    {"code": "002340", "name": "富国价值", "max_weight_limit": 0.15},
    {"code": "003096", "name": "中欧医疗", "max_weight_limit": 0.15},
    {"code": "sh512010", "name": "医药ETF", "max_weight_limit": 0.15},
]


def init_data():
    print(f"🚀 开始向 {API_URL} 导入数据...")
    for fund in funds:
        try:
            requests.post(API_URL, json=fund)
            print(f"✅ {fund['name']} OK")
        except:
            print(f"❌ {fund['name']} Fail")


if __name__ == "__main__":
    init_data()
