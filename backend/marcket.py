import requests
import yfinance as yf
from sqlmodel import Session, select
from db.database import engine
from db.models import Stock
from stock_open_api.api.eastmoney.company import get_company_info
import akshare as ak
import os
import contextlib
import time
import math


# === 🛡️ 网络工具 ===
@contextlib.contextmanager
def force_no_proxy():
    proxies = {}
    for key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"]:
        if key in os.environ:
            proxies[key] = os.environ[key]
            del os.environ[key]
    try:
        yield
    finally:
        for key, value in proxies.items():
            os.environ[key] = value


# ===============================
# 1. 批量引擎：东方财富 (更稳健的分页)
# ===============================
def fetch_ashare_industries():
    print("   📡 [批量引擎] 正在拉取全市场行业分类...")
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"

    # 降低每页数量，提高成功率
    page_size = 100

    params = {
        "pn": 1,
        "pz": page_size,
        "po": 1,
        "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f12,f14,f100",
    }

    mapping = {}

    try:
        with force_no_proxy():
            # 1. 获取总数
            res = requests.get(url, params=params, timeout=5)
            data = res.json()
            total = data["data"]["total"]
            total_pages = math.ceil(total / page_size)

            print(f"      - 目标: {total} 只股票, 共 {total_pages} 页")

            # 2. 循环抓取 (带重试)
            for page in range(1, total_pages + 1):
                params["pn"] = page
                success = False

                # 每页最多重试 2 次
                for retry in range(2):
                    try:
                        r = requests.get(url, params=params, timeout=5)
                        d = r.json()
                        if d["data"] and d["data"]["diff"]:
                            for item in d["data"]["diff"]:
                                if item["f100"] and item["f100"] != "-":
                                    mapping[item["f12"]] = item["f100"]
                            success = True
                            break  # 成功则跳出重试
                    except:
                        time.sleep(0.5)

                if not success:
                    print(f"      ⚠️ 第 {page} 页抓取失败")

            print(f"   ✅ [批量引擎] 索引完成: {len(mapping)}/{total}")
            return mapping

    except Exception as e:
        print(f"   ❌ [批量引擎] 崩溃: {e}")

    return mapping


# ===============================
# 2. 狙击引擎：单只股票查询 (核心修复)
# ===============================
def fetch_single_stock_industry(code: str):
    """
    针对漏网之鱼，直接查询单只股票详情
    """
    print(f"   🎯 [狙击引擎] 单独查询: {code} ...")

    # 构造 secid (688 开头是沪市 1，其他尝试 0 或 1)
    # 简单逻辑：6开头是沪市(1)，0/3开头是深市(0)，8/4/9是北交所(0)
    secid_prefix = "1" if code.startswith("6") else "0"
    secid = f"{secid_prefix}.{code}"

    url = "http://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f12,f14,f100",  # f100 是行业
        "invt": "2",
        "fltt": "2",
    }

    try:
        with force_no_proxy():
            res = requests.get(url, params=params, timeout=5)
            data = res.json()
            if data and data.get("data"):
                industry = data["data"].get("f100")
                if industry and industry != "-":
                    print(f"      -> 命中: {industry}")
                    return industry
    except Exception as e:
        print(f"      -> 失败: {e}")

    return None


# ===============================
# 2.5 F10 公司概况兜底接口
# ===============================
def fetch_company_survey_industry(code: str):
    """
    使用 stock-open-api SDK 作为 F10 行业兜底（调试版）
    """
    print(f"   🧬 [F10 引擎 SDK] 查询公司基本资料: {code} ...")
    try:
        info = get_company_info(code)

        print("====== F10 SDK RAW RETURN BEGIN ======")
        print(type(info))
        print(info)
        print("====== F10 SDK RAW RETURN END ======")

        if not isinstance(info, dict):
            print("      -> SDK 返回的不是 dict")
            return None

        industry = info.get("所属东财行业") or info.get("所属证监会行业")
        if industry:
            print(f"      -> SDK 命中行业: {industry}")
            return industry

    except Exception as e:
        print("====== F10 SDK EXCEPTION ======")
        print(repr(e))
        print("================================")

    return None


# ===============================
# 3. 海外引擎：Yahoo
# ===============================
SECTOR_TRANSLATION = {
    "Technology": "科技/电子",
    "Financial Services": "金融服务",
    "Communication Services": "通信/互联网",
    "Healthcare": "医药生物",
    "Consumer Cyclical": "可选消费",
    "Consumer Defensive": "日常消费",
    "Energy": "能源/石油",
    "Industrials": "工业制造",
    "Basic Materials": "基础化工",
    "Real Estate": "房地产",
    "Utilities": "公用事业",
}


def fetch_overseas_industry(code: str):
    y_code = code
    if code.isdigit() and len(code) == 5:
        y_code = f"{code}.HK"
    print(f"   📡 [海外引擎] 查询 {y_code} ...")
    try:
        ticker = yf.Ticker(y_code)
        info = ticker.info
        sector = info.get("sector")
        if sector:
            cn = SECTOR_TRANSLATION.get(sector, sector)
            print(f"      -> 识别: {cn}")
            return cn
    except:
        pass
    return "港股/海外"


# ===============================
# 4. 基金数据获取：AKShare
# ===============================
def fetch_fund_industry(symbol: str, year: str):
    """
    获取某只基金某年度的行业配置表
    """
    try:
        df = ak.fund_portfolio_industry_allocation_em(symbol=symbol, date=year)
        print(f"   📊 基金行业配置 {symbol} {year} 共 {len(df)} 条")
        return df
    except Exception as e:
        print(f"   ❌ 获取基金行业配置失败: {symbol} {year},", e)
        return None


def fetch_fund_holdings(symbol: str, year: str):
    """
    获取某只基金某年度的持仓明细
    """
    try:
        df = ak.fund_portfolio_hold_em(symbol=symbol, date=year)
        print(f"   📈 基金持仓明细 {symbol} {year} 共 {len(df)} 条")
        return df
    except Exception as e:
        print(f"   ❌ 获取基金持仓明细失败: {symbol} {year},", e)
        return None


def infer_stock_industry_from_funds(stock_code: str, fund_list: list, year: str):
    """
    利用基金行业配置 + 持仓明细推断股票行业
    -----------------------------
    stock_code: 股票代码字符串（如 "688169"）
    fund_list: 可能持有这个股票的基金代码列表（如 ["000001","000002"...]）
    year: 某个年份（如 "2024"）

    返回: (primary_industry, industry_scores) 或 (None, {})
    """
    print(f"   🔍 [基金推断引擎] 通过基金持仓推断股票行业: {stock_code} ...")
    industry_scores = {}  # 行业对应的累计权重得分

    for fund in fund_list:
        # 1. 拿行业配置
        try:
            df_ind = ak.fund_portfolio_industry_allocation_em(symbol=fund, date=year)
        except Exception:
            continue
        if df_ind is None or df_ind.empty:
            continue

        # 2. 拿持仓明细
        try:
            df_hold = ak.fund_portfolio_hold_em(symbol=fund, date=year)
        except Exception:
            continue
        if df_hold is None or df_hold.empty:
            continue

        # 3. 过滤出这个基金是否持有该股票
        # 注意：列名可能是 '股票代码' 或 '代码'，需要根据实际情况调整
        stock_column = None
        for col in df_hold.columns:
            if "代码" in str(col) or "code" in str(col).lower():
                stock_column = col
                break

        if stock_column is None:
            continue

        df_stock = df_hold[
            df_hold[stock_column].astype(str).str.contains(stock_code, na=False)
        ]
        if df_stock.empty:
            continue

        # 4. 如果持有，则按行业权重累加
        # 假设 industry allocation 按行业配置百分比计算
        # 注意：列名可能是 '行业类别' 或 '行业'，'占净值比例' 或 '比例'
        industry_column = None
        weight_column = None

        for col in df_ind.columns:
            if "行业" in str(col) or "industry" in str(col).lower():
                industry_column = col
            if "比例" in str(col) or "weight" in str(col).lower() or "净值" in str(col):
                weight_column = col

        if industry_column and weight_column:
            for _, row in df_ind.iterrows():
                industry = str(row[industry_column])
                try:
                    weight = float(row[weight_column]) / 100.0
                except (ValueError, TypeError):
                    continue
                industry_scores[industry] = industry_scores.get(industry, 0.0) + weight

    # 5. 选出得分最高的行业作为最终推断
    if not industry_scores:
        print(f"      -> 未找到持有该股票的基金")
        return None, {}

    # 返回行业得分字典和最高得分行业
    primary_industry = max(industry_scores, key=industry_scores.get)
    print(
        f"      -> 推断行业: {primary_industry} (得分: {industry_scores[primary_industry]:.4f})"
    )
    return primary_industry, industry_scores


# ===============================
# 主任务
# ===============================
def auto_update_industries_task():
    print("🤖 [后台任务] 开始行业信息补全...")

    with Session(engine) as session:
        unknown_stocks = session.exec(
            select(Stock).where(Stock.industry == "未分类")
        ).all()

        if not unknown_stocks:
            print("   ✨ 所有股票行业信息已完善。")
            return

        print(f"   🔍 发现 {len(unknown_stocks)} 只未分类股票")

        # 1. 只有当缺失股票较多时(>5)，才启用批量引擎
        # 否则直接用狙击引擎，效率更高
        ashare_map = {}
        if len(unknown_stocks) > 5:
            ashare_map = fetch_ashare_industries()
        else:
            print("   ⏩ 缺失数量少，跳过批量抓取，直接启用狙击模式")

        updated_count = 0

        for stock in unknown_stocks:
            new_ind = None

            # 优先查批量表
            if stock.code in ashare_map:
                new_ind = ashare_map[stock.code]

            # 如果没查到，启用单点狙击 (A股行情接口)
            if not new_ind and stock.code.isdigit() and len(stock.code) == 6:
                new_ind = fetch_single_stock_industry(stock.code)

            # 🔥 F10 公司概况兜底（核心升级点）
            if not new_ind and stock.code.isdigit() and len(stock.code) == 6:
                new_ind = fetch_company_survey_industry(stock.code)

            # 如果还是没查到，试海外
            if not new_ind and (len(stock.code) == 5 or not stock.code.isdigit()):
                new_ind = fetch_overseas_industry(stock.code)
                time.sleep(1)

            if new_ind:
                print(f"      + {stock.name}: {stock.industry} -> {new_ind}")
                stock.industry = new_ind
                session.add(stock)
                updated_count += 1
            else:
                print(f"      ⚠️ 依然无法识别: {stock.name} ({stock.code})")

        session.commit()
        print(f"✅ [后台任务] 完成。成功补全 {updated_count} 只股票。")

        # --- 基金数据补全（在需要的时候运行） ---
        # 这里 symbol 用基金代码，不是股票代码
        fund_codes = ["000001", "000002"]  # 你要补全的基金列表
        target_years = ["2023", "2024"]  # 想抓取哪些年份的数据

        for fund_code in fund_codes:
            for y in target_years:
                df_ind = fetch_fund_industry(fund_code, y)
                # 数据已获取，可根据需要进行处理

                df_hold = fetch_fund_holdings(fund_code, y)
                # 数据已获取，可根据需要进行处理


if __name__ == "__main__":
    auto_update_industries_task()
