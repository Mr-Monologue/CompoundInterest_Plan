import akshare as ak
from sqlmodel import Session, select
from db.database import engine
from db.models import Stock
import os
import contextlib


# === 🛡️ 核弹级强制直连工具 ===
@contextlib.contextmanager
def force_no_proxy():
    # 1. 备份现有环境
    backup = {
        k: os.environ.get(k)
        for k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"]
    }

    try:
        # 2. 彻底屏蔽代理
        # 设置为空字符串通常能覆盖系统设置，
        # 设置 NO_PROXY=* 是告诉 requests 对所有域名都不使用代理
        os.environ["http_proxy"] = ""
        os.environ["https_proxy"] = ""
        os.environ["HTTP_PROXY"] = ""
        os.environ["HTTPS_PROXY"] = ""
        os.environ["NO_PROXY"] = "*"
        yield
    finally:
        # 3. 恢复环境
        for k, v in backup.items():
            if v is None:
                if k in os.environ:
                    del os.environ[k]
            else:
                os.environ[k] = v


def get_static_industry_map():
    """
    Plan B: 常用核心资产行业映射表 (离线兜底)
    包含公募基金最爱买的前50大重仓股，防止网络请求失败时无法分类。
    """
    return {
        # === 白酒/消费 ===
        "600519": "酿酒行业",  # 茅台
        "000858": "酿酒行业",  # 五粮液
        "000568": "酿酒行业",  # 泸州老窖
        "600809": "酿酒行业",  # 山西汾酒
        "002304": "酿酒行业",  # 洋河
        "600887": "食品饮料",  # 伊利
        "000273": "食品饮料",  # 青岛啤酒
        "603288": "食品饮料",  # 海天
        "002027": "文化传媒",  # 分众传媒 (对应你的持仓)
        "09987": "旅游酒店",  # 百胜中国-S (你的持仓)
        # === 医药/医疗 ===
        "600276": "化学制药",  # 恒瑞
        "300760": "医疗器械",  # 迈瑞
        "300015": "医疗服务",  # 爱尔
        "603259": "医疗服务",  # 药明康德
        "300832": "医疗器械",  # 新产业 (你的持仓)
        "688617": "医疗器械",  # 惠泰医疗 (你的持仓)
        "000661": "生物制品",  # 长春高新
        # === 新能源/光伏/车 ===
        "300750": "电池",  # 宁德时代
        "002594": "汽车整车",  # 比亚迪
        "601012": "光伏设备",  # 隆基
        "300274": "光伏设备",  # 阳光电源
        # === 科技/电子 ===
        "603501": "半导体",  # 韦尔
        "688981": "半导体",  # 中芯国际
        "002475": "消费电子",  # 立讯精密
        "002415": "计算机设备",  # 海康威视
        # === 金融 ===
        "600036": "银行",  # 招行
        "601318": "保险",  # 平安
        "600030": "证券",  # 中信
        "002142": "银行",  # 宁波银行
        "000776": "证券",  # 广发证券
        # === 🔥 新增：根据你的报错日志补全 🔥 ===
        # 消费/家电
        "000333": "家电行业",  # 美的集团
        "600690": "家电行业",  # 海尔智家
        "000651": "家电行业",  # 格力电器
        "301061": "家电行业",  # 匠心家居
        "605499": "食品饮料",  # 东鹏饮料
        "002507": "食品饮料",  # 涪陵榨菜
        "603605": "美容护理",  # 珀莱雅
        "600660": "汽车零部件",  # 福耀玻璃
        "600600": "酿酒行业",  # 青岛啤酒
        # 科技/电子/通信
        "300394": "通信设备",  # 天孚通信
        "300502": "通信设备",  # 新易盛
        "002222": "电子元件",  # 福晶科技
        "002558": "游戏",  # 巨人网络
        "002517": "游戏",  # 恺英网络
        "688036": "消费电子",  # 传音控股
        # 医药/医疗
        "300759": "医疗服务",  # 康龙化成
        "688506": "化学制药",  # 百利天恒
        "002821": "医疗服务",  # 凯莱英
        "300347": "医疗服务",  # 泰格医药
        "002294": "化学制药",  # 信立泰
        "002422": "化学制药",  # 科伦药业
        "688235": "化学制药",  # 百济神州
        "002653": "化学制药",  # 海思科
        "688583": "医疗器械",  # 思看科技
        # 周期/制造/其他
        "002225": "耐火材料",  # 濮耐股份
        "603950": "汽车零部件",  # 长源东谷
        "001301": "电池",  # 尚太科技
        "002245": "电池",  # 蔚蓝锂芯
        "600212": "输配电气",  # 绿能慧充
        "002311": "农牧饲渔",  # 海大集团
        "301345": "交运设备",  # 涛涛车业
        "301004": "家用轻工",  # 嘉益股份
        "000526": "教育",  # 学大教育
        "603518": "纺织服装",  # 锦泓集团
        "601899": "有色金属",  # 紫金矿业
        "000425": "工程机械",  # 徐工机械
        "603129": "交运设备",  # 春风动力
        "600547": "贵金属",  # 山东黄金
        "603979": "有色金属",  # 金诚信
        # === 港股/美股 (兼容纯数字代码) ===
        "00700": "互联网",
        "09988": "互联网",
        "03690": "互联网",
        "01024": "互联网",
        "06618": "医疗保健",
        "00883": "石油石化",
        "00941": "通信运营商",
    }


def update_stock_industries():
    print("🚀 开始更新行业分类数据...")

    # 1. 加载静态兜底数据 (保证基础核心资产一定有行业)
    industry_map = get_static_industry_map()
    print(f"   📦 已加载内置静态数据: {len(industry_map)} 条")

    # 2. 尝试联网获取全量 A 股数据 (东方财富)
    try:
        print("   📡 正在尝试直连拉取全量 A股 数据 (可能会慢)...")
        with force_no_proxy():
            # 这个接口数据量大，网络不好容易超时
            df_a = ak.stock_board_industry_name_em()

        if df_a is not None and not df_a.empty:
            count = 0
            for _, row in df_a.iterrows():
                # 覆盖/新增到映射表中
                industry_map[row["股票代码"]] = row["板块名称"]
                count += 1
            print(f"   ✅ 联网更新成功，覆盖 {count} 只 A股股票")
        else:
            print("   ⚠️ 接口返回空数据，将使用静态兜底数据")

    except Exception as e:
        print(f"   ⚠️ 网络获取失败 (将使用静态数据): {e}")

    # 3. 更新数据库
    print("\n💾 正在写入数据库...")
    with Session(engine) as session:
        # 查出所有"未分类"的股票
        stocks = session.exec(select(Stock).where(Stock.industry == "未分类")).all()

        if not stocks:
            print("   ✨ 没有需要更新的股票 (全都有行业了)")
            return

        print(f"   🔍 发现 {len(stocks)} 只待补全股票")

        updated_count = 0
        for stock in stocks:
            # 尝试匹配
            if stock.code in industry_map:
                new_ind = industry_map[stock.code]
                print(f"      - {stock.name} ({stock.code}) -> {new_ind}")

                stock.industry = new_ind
                session.add(stock)
                updated_count += 1
            else:
                # 实在找不到的，如果是港股(5位)，尝试标为港股
                if len(stock.code) == 5:
                    stock.industry = "港股/海外"
                    session.add(stock)
                    updated_count += 1
                    print(
                        f"      - {stock.name} ({stock.code}) -> 港股/海外 (自动归类)"
                    )
                else:
                    print(f"      ❌ 未找到: {stock.name} ({stock.code})")

        session.commit()
        print(f"🎉 更新完成！成功补全 {updated_count} 只股票。")


if __name__ == "__main__":
    update_stock_industries()
