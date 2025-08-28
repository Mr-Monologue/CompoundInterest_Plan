#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心动作封装（由 GUI 调用）
"""

import logging
import pandas as pd
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any

from ..core.config import load_all_funds_config, save_config
from ..core.data_sources import (
    get_latest_nav_with_fallback,
    get_index_data_with_fallback,
)
from ..core.signals import calculate_ma200_deviation, calculate_dca_allocation
from ..core.holdings import HoldingsCalculator
from ..db.storage import connect_db, init_db, get_latest_data_for_fund

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def sample_and_store_one(fund_cfg: dict) -> dict:
    """抓取净值&指数→算偏离与建议→写 v2 表→更新 fund_state，返回结果供 GUI 展示"""
    fund_code = fund_cfg["fund_code"]
    today = date.today().isoformat()
    now_ts = int(datetime.now().timestamp())

    # 1) NAV & 代理指数
    nav, nav_src, _ = get_latest_nav_with_fallback(
        fund_cfg["fund_code"], fund_cfg["fund_name_en"]
    )
    df_idx, idx_src, _ = get_index_data_with_fallback(
        fund_cfg["proxy_index"], fund_cfg["proxy_index_en"]
    )

    if "ma200" not in df_idx.columns:
        df_idx["ma200"] = df_idx["close"].rolling(200).mean()

    dev = calculate_ma200_deviation(df_idx, nav)

    # 2) 状态 & 建议
    with connect_db() as con:
        row = con.execute(
            "SELECT reserve_balance, last_signal_date, last_low_trigger_date FROM fund_state WHERE fund_code=?",
            (fund_code,),
        ).fetchone()
        state = {"reserve_balance": (row[0] if row else 0.0)}
    plan = calculate_dca_allocation(fund_cfg, state, dev)

    # 3) 持仓快照
    hold = HoldingsCalculator(fund_cfg).calculate_holdings_summary(nav)

    # 4) persist
    last = df_idx.iloc[-1]
    with connect_db() as con:
        con.execute(
            "INSERT OR REPLACE INTO nav_daily_v2 VALUES (?,?,?,?,?)",
            (fund_code, today, float(nav), nav_src, now_ts),
        )
        con.execute(
            """INSERT OR REPLACE INTO proxy_daily_v2
                       (fund_code,date,close,ma200,dev_pct,source,timestamp)
                       VALUES (?,?,?,?,?,?,?)""",
            (
                fund_code,
                today,
                float(last["close"]),
                float(last["ma200"]),
                float(dev["deviation_pct"]),
                idx_src,
                now_ts,
            ),
        )
        con.execute(
            """INSERT OR REPLACE INTO dca_plan_v2
                       (fund_code,date,level,dev_pct,base_amt,dyn_amt,total_amt,reserve_before,reserve_after,timestamp)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                fund_code,
                today,
                plan["level"],
                plan["deviation_pct"],
                plan["fixed_amount"],
                plan["dynamic_amount"],
                plan["total_amount"],
                plan["reserve_before"],
                plan["reserve_after"],
                now_ts,
            ),
        )
        con.execute(
            """INSERT OR REPLACE INTO holdings_snapshot_v2
                       (fund_code,date,units,avg_cost,nav,mtm,unreal_pnl,unreal_pct,total_pnl,timestamp)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                fund_code,
                today,
                hold["units"],
                hold["avg_cost"],
                hold["current_nav"],
                hold["market_value"],
                hold["unrealized_pnl"],
                hold["unrealized_pct"],
                hold["total_pnl"],
                now_ts,
            ),
        )
        # state
        con.execute(
            """INSERT INTO fund_state(fund_code,reserve_balance,last_signal_date,last_low_trigger_date,updated_at)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(fund_code) DO UPDATE SET
                         reserve_balance=excluded.reserve_balance,
                         last_signal_date=excluded.last_signal_date,
                         last_low_trigger_date=excluded.last_low_trigger_date,
                         updated_at=excluded.updated_at""",
            (
                fund_code,
                float(plan["reserve_after"]),
                today,
                today if plan["level"] == "low" else (row[2] if row else None),
                now_ts,
            ),
        )

    return {
        "fund_code": fund_code,
        "nav": nav,
        "nav_src": nav_src,
        "dev": dev,
        "plan": plan,
        "hold": hold,
        "idx_src": idx_src,
    }


def add_fund_to_config(new_fund: dict):
    """添加新基金到配置"""
    funds, cfg = load_all_funds_config()
    # 简单重复检查
    if any(f["fund_code"] == new_fund["fund_code"] for f in funds):
        raise ValueError("基金代码已存在")
    cfg["funds"].append(new_fund)
    save_config(cfg)


# 兼容性函数（保持原有接口）
def run_daily_task_for_all_funds() -> List[Dict[str, Any]]:
    """为所有基金执行每日任务"""
    logger.info("开始执行每日任务...")
    init_db()
    funds, _ = load_all_funds_config()
    results = []

    for fund_config in funds:
        try:
            result = sample_and_store_one(fund_config)
            results.append(result)
            logger.info(
                f"[{result['fund_code']}] NAV={result['nav']:.4f} src={result['nav_src']} "
                f"dev={result['dev']['deviation_pct']:.2f}% level={result['plan']['level']} "
                f"plan={result['plan']['total_amount']:.2f}"
            )
        except Exception as e:
            logger.error(f"基金 {fund_config['fund_code']} 执行失败: {e}")
            results.append(
                {
                    "fund_code": fund_config["fund_code"],
                    "error": str(e),
                    "success": False,
                }
            )

    logger.info(f"每日任务完成，共处理 {len(results)} 个基金")
    return results


def run_once_for_fund(fund_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """为单个基金执行一次完整的数据采集和分析（兼容性函数）"""
    return sample_and_store_one(fund_cfg)


def get_fund_latest_data(fund_code: str) -> Optional[Dict[str, Any]]:
    """获取基金最新数据"""
    data = get_latest_data_for_fund(fund_code)
    required_keys = ["nav", "proxy", "plan", "holdings"]
    if not all(key in data for key in required_keys):
        return None
    data["fund_code"] = fund_code
    return data


def get_portfolio_summary() -> pd.DataFrame:
    """获取投资组合汇总"""
    funds, _ = load_all_funds_config()
    rows = []

    for fund_config in funds:
        fund_code = fund_config["fund_code"]
        data = get_fund_latest_data(fund_code)

        if data:
            rows.append(
                {
                    "基金": f"{fund_code} {fund_config['fund_name']}",
                    "最新净值": data["nav"]["value"],
                    "估值偏离(%)": data["proxy"]["dev_pct"],
                    "估值层级": data["plan"]["level"].upper(),
                    "本周建议(¥)": data["plan"]["total_amt"],
                    "固定(¥)": data["plan"]["base_amt"],
                    "动态(¥)": data["plan"]["dyn_amt"],
                    "准备金余(¥)": data["plan"]["reserve_after"],
                    "数据日期": data["nav"]["date"],
                }
            )

    if rows:
        df = pd.DataFrame(rows).sort_values("估值偏离(%)")
        return df
    else:
        return pd.DataFrame()


def clear_all_cache():
    """清除所有缓存"""
    try:
        import streamlit as st

        st.cache_data.clear()
        logger.info("Streamlit 缓存已清除")
    except ImportError:
        logger.info("Streamlit 未安装，跳过缓存清除")
    except Exception as e:
        logger.warning(f"清除缓存失败: {e}")


def export_fund_data(fund_code: str, format: str = "csv") -> str:
    """导出基金数据"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    with connect_db() as con:
        nav_df = pd.read_sql(
            "SELECT * FROM nav_daily_v2 WHERE fund_code=? ORDER BY date",
            con,
            params=[fund_code],
        )
        proxy_df = pd.read_sql(
            "SELECT * FROM proxy_daily_v2 WHERE fund_code=? ORDER BY date",
            con,
            params=[fund_code],
        )
        plan_df = pd.read_sql(
            "SELECT * FROM dca_plan_v2 WHERE fund_code=? ORDER BY date",
            con,
            params=[fund_code],
        )
        holdings_df = pd.read_sql(
            "SELECT * FROM holdings_snapshot_v2 WHERE fund_code=? ORDER BY date",
            con,
            params=[fund_code],
        )

    if format.lower() == "csv":
        filename = f"export_{fund_code}_{timestamp}.csv"
        combined_df = nav_df.merge(
            proxy_df, on=["fund_code", "date"], suffixes=("_nav", "_proxy")
        )
        combined_df = combined_df.merge(
            plan_df, on=["fund_code", "date"], suffixes=("", "_plan")
        )
        combined_df = combined_df.merge(
            holdings_df, on=["fund_code", "date"], suffixes=("", "_holdings")
        )
        combined_df.to_csv(filename, index=False, encoding="utf-8-sig")
    else:
        filename = f"export_{fund_code}_{timestamp}.json"
        data = {
            "nav": nav_df.to_dict("records"),
            "proxy": proxy_df.to_dict("records"),
            "plan": plan_df.to_dict("records"),
            "holdings": holdings_df.to_dict("records"),
        }
        import json

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"数据已导出到: {filename}")
    return filename


def update_fund_in_config(fund_code: str, fund_data: Dict[str, Any]) -> bool:
    """更新基金配置"""
    try:
        funds, raw_cfg = load_all_funds_config()
        for i, fund in enumerate(raw_cfg["funds"]):
            if fund["fund_code"] == fund_code:
                raw_cfg["funds"][i] = fund_data
                break
        else:
            logger.warning(f"未找到基金代码: {fund_code}")
            return False

        success = save_config(raw_cfg, "data/config.json")
        if success:
            logger.info(f"成功更新基金: {fund_code}")
        return success
    except Exception as e:
        logger.error(f"更新基金失败: {e}")
        return False


def delete_fund_from_config(fund_code: str) -> bool:
    """从配置中删除基金"""
    try:
        funds, raw_cfg = load_all_funds_config()
        original_count = len(raw_cfg["funds"])
        raw_cfg["funds"] = [f for f in raw_cfg["funds"] if f["fund_code"] != fund_code]

        if len(raw_cfg["funds"]) == original_count:
            logger.warning(f"未找到基金代码: {fund_code}")
            return False

        success = save_config(raw_cfg, "data/config.json")
        if success:
            logger.info(f"成功删除基金: {fund_code}")
        return success
    except Exception as e:
        logger.error(f"删除基金失败: {e}")
        return False


def get_fund_config(fund_code: str) -> Optional[Dict[str, Any]]:
    """获取指定基金的配置"""
    try:
        funds, _ = load_all_funds_config()
        for fund in funds:
            if fund["fund_code"] == fund_code:
                return fund
        return None
    except Exception as e:
        logger.error(f"获取基金配置失败: {e}")
        return None


def validate_fund_data(fund_data: Dict[str, Any]) -> tuple[bool, List[str]]:
    """验证基金数据"""
    errors = []
    required_fields = [
        "fund_code",
        "fund_name",
        "fund_name_en",
        "proxy_index",
        "proxy_index_en",
    ]
    for field in required_fields:
        if not fund_data.get(field):
            errors.append(f"缺少必填字段: {field}")

    if fund_data.get("weekly_budget", 0) <= 0:
        errors.append("周预算必须大于0")

    holdings = fund_data.get("manual_holdings", {})
    if holdings.get("enabled", False):
        if holdings.get("units_left", 0) < 0:
            errors.append("持有份额不能为负数")
        if holdings.get("avg_cost", 0) < 0:
            errors.append("平均成本不能为负数")

    return len(errors) == 0, errors


if __name__ == "__main__":
    # 测试服务层功能
    print("服务层测试")
    results = run_daily_task_for_all_funds()
    print(f"处理了 {len(results)} 个基金")

    summary = get_portfolio_summary()
    if not summary.empty:
        print("\n投资组合汇总:")
        print(summary.to_string(index=False))
    else:
        print("暂无数据")


# --- 周复盘文字生成器 ---
from ..db.storage import query_df

LEVEL_ORDER = ["low", "mid", "high"]


def _level_counts(df: pd.DataFrame) -> dict:
    """统计各估值层级的天数"""
    out = {k: 0 for k in LEVEL_ORDER}
    for k, v in df["level"].value_counts().to_dict().items():
        out[k] = int(v)
    return out


def _one_fund_week_summary(code: str, df: pd.DataFrame) -> str:
    """生成单个基金的周复盘摘要"""
    df = df.sort_values("date")
    lv = _level_counts(df)
    total_amt = df["total_amt"].sum()
    base_sum = df["base_amt"].sum() if "base_amt" in df.columns else float("nan")
    dyn_sum = df["dyn_amt"].sum() if "dyn_amt" in df.columns else float("nan")
    avg_dev = df["dev_pct"].mean()
    min_dev = df["dev_pct"].min()
    max_dev = df["dev_pct"].max()
    last_row = df.iloc[-1]
    first_row = df.iloc[0]
    res_chg = last_row["reserve_after"] - first_row.get("reserve_before", 0.0)

    # 最近一天的估值层级 & 建议口径
    last_level = str(last_row["level"])
    if last_level == "low":
        advice = "估值偏低，建议加大投入（在不超'周投入上限'的前提下动用准备金）。"
    elif last_level == "mid":
        advice = "估值合理，维持固定投入为主，动态部分按平滑比例谨慎使用准备金。"
    else:
        advice = "估值偏高，建议仅保留固定投入或暂缓；准备金以累积为主。"

    # 文案
    lines = [
        f"**[{code}] 周复盘摘要**",
        f"- 统计区间：{df['date'].iloc[0]} → {df['date'].iloc[-1]}（共 {len(df)} 天）",
        f"- 估值分布：低估 {lv['low']} 天 / 合理 {lv['mid']} 天 / 偏高 {lv['high']} 天",
        f"- 偏离度：平均 {avg_dev:.2f}%，最低 {min_dev:.2f}%，最高 {max_dev:.2f}%",
        f"- 投入合计：¥{total_amt:.2f}（固定 ¥{base_sum:.2f}，动态 ¥{dyn_sum:.2f}）",
        f"- 准备金变化：{('+' if res_chg>=0 else '')}{res_chg:.2f} → 当前余额 ¥{last_row['reserve_after']:.2f}",
        f"- 最新估值层级：**{last_level.upper()}**；策略建议：{advice}",
    ]
    # 额外提示：若本周曾触达低估阈值但当天未充分动用准备金
    if (lv["low"] > 0) and (dyn_sum < base_sum * 0.5):  # 阈值可按需调整
        lines.append(
            "⚠️ 本周有低估时段，但动态投入偏少，可评估是否适度提高动用比例或上限。"
        )
    return "\n".join(lines)


def generate_weekly_narrative(fund_code: str | None = None, days: int = 7) -> str:
    """
    生成最近 N 天的自然语言复盘；fund_code=None 时输出组合层总览 + 各基金摘要
    """
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    if fund_code:
        df = query_df(
            """SELECT fund_code,date,level,dev_pct,base_amt,dyn_amt,total_amt,
                      reserve_before,reserve_after
               FROM dca_plan_v2
               WHERE fund_code=? AND date>=? ORDER BY date""",
            (fund_code, start),
        )
        if df.empty:
            return f"[{fund_code}] 最近 {days} 天无记录，可在侧边栏点'采样并保存'。"
        return _one_fund_week_summary(fund_code, df)

    # 组合层
    df_all = query_df(
        """SELECT fund_code,date,level,dev_pct,base_amt,dyn_amt,total_amt,
                  reserve_before,reserve_after
           FROM dca_plan_v2
           WHERE date>=? ORDER BY fund_code,date""",
        (start,),
    )
    if df_all.empty:
        return f"组合最近 {days} 天无数据，请先对各基金进行'采样并保存'。"

    # 组合级别的总体结论
    total_amt = df_all["total_amt"].sum()
    base_sum = df_all["base_amt"].sum()
    dyn_sum = df_all["dyn_amt"].sum()
    avg_dev = df_all.groupby("fund_code")["dev_pct"].mean().mean()
    low_days = (df_all["level"] == "low").sum()
    mid_days = (df_all["level"] == "mid").sum()
    high_days = (df_all["level"] == "high").sum()
    lines = [
        f"**组合周复盘（最近 {days} 天）**",
        f"- 组合投入合计：¥{total_amt:.2f}（固定 ¥{base_sum:.2f}，动态 ¥{dyn_sum:.2f}）",
        f"- 估值分布（按日汇总）：低估 {low_days} / 合理 {mid_days} / 偏高 {high_days}",
        f"- 各基金平均偏离度均值：{avg_dev:.2f}%",
    ]
    if dyn_sum < base_sum * 0.3 and low_days > 0:
        lines.append("⚠️ 本周出现低估，但整体动态投入较保守；可考虑提高准备金动用比例。")

    # 各基金一段话
    for code, sub in df_all.groupby("fund_code"):
        lines.append("")
        lines.append(_one_fund_week_summary(code, sub.reset_index(drop=True)))

    return "\n".join(lines)
