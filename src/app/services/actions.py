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
try:
    from ..core.data_sources import (
        get_latest_nav_with_fallback,
        get_index_data_with_fallback,
    )
except ImportError:
    get_latest_nav_with_fallback = None
    get_index_data_with_fallback = None
from ..db.storage import connect_db, init_db, get_latest_data_for_fund

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def sample_and_store_one(fund_cfg: dict) -> dict:
    """抓取净值&指数→算偏离与建议→写 v2 表→更新 fund_state，返回结果供 GUI 展示
    
    实盘辅助关键修正：
    - dev_pct 必须基于代理指数(proxy_close/ma200)，不得使用基金净值
    - 所有建议输出前必须经过 risk_guard
    - 持仓计算使用 accounting 模块（Decimal 精度）
    """
    from ..core.strategy import (
        calculate_ma200_deviation,
        calculate_dca_allocation as calc_dca,
    )
    from ..core.risk_guard import advice_allowed, RiskResult
    from ..services.accounting import calculate_holdings as calc_holdings
    
    fund_code = fund_cfg["fund_code"]
    today = date.today().isoformat()
    now_ts = int(datetime.now().timestamp())

    # 1) NAV & 代理指数 ── 分开获取
    nav, nav_src, _ = get_latest_nav_with_fallback(
        fund_cfg["fund_code"], fund_cfg["fund_name_en"]
    )
    df_idx, idx_src, idx_status = get_index_data_with_fallback(
        fund_cfg["proxy_index"], fund_cfg["proxy_index_en"]
    )

    if df_idx.empty or "close" not in df_idx.columns:
        return {
            "fund_code": fund_code,
            "error": "代理指数数据为空",
            "risk_guard": RiskResult(passed=False, errors=["代理指数数据为空"]).__dict__,
        }

    if "ma200" not in df_idx.columns or df_idx["ma200"].iloc[-1] != df_idx["ma200"].iloc[-1]:
        df_idx["ma200"] = df_idx["close"].rolling(200).mean()

    last = df_idx.iloc[-1]
    proxy_close = float(last["close"])
    proxy_ma200 = float(last["ma200"])

    # 2) MA200 偏离度 ── 关键：使用代理指数，不使用基金净值！
    try:
        dev_pct = calculate_ma200_deviation(proxy_close, proxy_ma200)
    except ValueError as e:
        return {
            "fund_code": fund_code,
            "error": f"MA200计算失败: {e}",
            "risk_guard": RiskResult(passed=False, errors=[str(e)]).__dict__,
        }
    level = "low" if dev_pct <= -0.10 else ("mid" if dev_pct <= 0.05 else "high")

    dev = {
        "current_price": proxy_close,    # 修正：这是代理指数价格，不是基金净值
        "ma200": proxy_ma200,
        "deviation_pct": dev_pct,
        "level": level,
        "date": str(last.get("date", today)),
    }

    # 3) 读取准备金状态
    with connect_db() as con:
        row = con.execute(
            "SELECT reserve_balance, last_signal_date, last_low_trigger_date FROM fund_state WHERE fund_code=?",
            (fund_code,),
        ).fetchone()
        reserve_balance = float(row[0]) if row else 0.0

    # 4) 定投建议 ── 使用新策略模块
    plan_result = calc_dca(fund_cfg, reserve_balance, dev_pct)

    # 5) 持仓计算 ── 使用 accounting 模块 (Decimal 精度)
    hcfg = fund_cfg.get("manual_holdings", {})
    if hcfg.get("enabled") and nav is not None:
        try:
            holding = calc_holdings(
                units=hcfg["units_left"],
                avg_cost=hcfg["avg_cost"],
                current_nav=nav,
                realized_pnl=hcfg.get("realized_pnl", 0.0),
            )
            hold = {
                "units": float(holding.units),
                "avg_cost": float(holding.avg_cost),
                "current_nav": float(holding.current_nav),
                "market_value": float(holding.market_value),
                "unrealized_pnl": float(holding.unrealized_pnl),
                "unrealized_pct": float(holding.unrealized_pct),
                "total_pnl": float(holding.total_pnl),
                "breakeven_nav": float(holding.breakeven_nav),
            }
        except ValueError as e:
            hold = {"error": str(e), "units": 0, "market_value": 0, "unrealized_pnl": 0, "unrealized_pct": 0, "total_pnl": 0}
    else:
        hold = {"units": 0, "market_value": 0, "unrealized_pnl": 0, "unrealized_pct": 0, "total_pnl": 0}

    # 6) risk_guard ── 生成建议前最后一道防线
    risk = advice_allowed(
        nav=nav,
        proxy_close=proxy_close,
        ma200=proxy_ma200,
        dev_pct=dev_pct,
        source=idx_src,
        plan=plan_result,
        weekly_budget=fund_cfg.get("weekly_budget", 200.0),
    )

    plan = {
        "level": plan_result.level,
        "deviation_pct": dev_pct,
        "fixed_amount": plan_result.fixed_amount,
        "dynamic_amount": plan_result.dynamic_amount,
        "total_amount": plan_result.total_amount,
        "reserve_before": plan_result.reserve_before,
        "reserve_after": plan_result.reserve_after,
    }

    # 7) 持久化（仅当数据可信时写入建议数据）
    with connect_db() as con:
        con.execute(
            "INSERT OR REPLACE INTO nav_daily_v2 VALUES (?,?,?,?,?)",
            (fund_code, today, float(nav) if nav else 0, nav_src, now_ts),
        )
        con.execute(
            """INSERT OR REPLACE INTO proxy_daily_v2
                       (fund_code,date,close,ma200,dev_pct,source,timestamp)
                       VALUES (?,?,?,?,?,?,?)""",
            (fund_code, today, proxy_close, proxy_ma200, dev_pct, idx_src, now_ts),
        )
        con.execute(
            """INSERT OR REPLACE INTO dca_plan_v2
                       (fund_code,date,level,dev_pct,base_amt,dyn_amt,total_amt,reserve_before,reserve_after,timestamp)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                fund_code, today,
                plan["level"], plan["deviation_pct"],
                plan["fixed_amount"], plan["dynamic_amount"],
                plan["total_amount"],
                plan["reserve_before"], plan["reserve_after"],
                now_ts,
            ),
        )
        con.execute(
            """INSERT OR REPLACE INTO holdings_snapshot_v2
                       (fund_code,date,units,avg_cost,nav,mtm,unreal_pnl,unreal_pct,total_pnl,timestamp)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                fund_code, today,
                hold.get("units", 0), hold.get("avg_cost", 0),
                hold.get("current_nav", nav or 0),
                hold.get("market_value", 0), hold.get("unrealized_pnl", 0),
                hold.get("unrealized_pct", 0), hold.get("total_pnl", 0),
                now_ts,
            ),
        )
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
                plan["reserve_after"],
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
        "risk_guard": risk.__dict__,
        "advice_allowed": risk.passed,
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


# ── Dry-run CLI ─────────────────────────────────────────

def dry_run_all(output_format: str = "json", offline: bool = False) -> None:
    """对所有基金执行 dry-run，输出审计链。

    offline=True: 只从已有数据库读取最新数据，不做任何网络请求。
    offline=False: 调用 sample_and_store_one（可能触发网络请求）。
    """
    import json as _json

    if offline:
        results = _dry_run_offline()
    else:
        results = _dry_run_live()

    if output_format == "json":
        print(_json.dumps(results, ensure_ascii=False, indent=2, default=str))
    elif output_format == "table":
        print(f"{'Code':<8} {'NAV':>8} {'Dev%':>8} {'Trusted':>8} {'Guard':>8} {'Fixed':>8} {'Dyn':>8} {'Reserve':>8}")
        print("-" * 72)
        for e in results:
            print(
                f"{e.get('fund_code','?'):<8} "
                f"{e.get('fund_nav') or '?':>8} "
                f"{e.get('dev_pct',0)*100 if e.get('dev_pct') else 0:>7.2f}% "
                f"{'YES' if e.get('is_trusted') else 'NO':>8} "
                f"{'PASS' if e.get('risk_guard_passed') else 'FAIL':>8} "
                f"{e.get('fixed_amount') or 0:>8.1f} "
                f"{e.get('dynamic_amount') or 0:>8.1f} "
                f"{e.get('reserve_after') or 0:>8.1f}"
            )


def _dry_run_offline() -> list:
    """离线 dry-run：仅从数据库读取最新数据，应用 risk_guard + 策略计算。"""
    from ..core.risk_guard import advice_allowed
    from ..core.strategy import calculate_dca_allocation as calc_dca

    results = []
    with connect_db() as con:
        fund_codes = [
            r[0] for r in con.execute(
                "SELECT DISTINCT fund_code FROM nav_daily_v2 ORDER BY fund_code"
            ).fetchall()
        ]

    funds, _ = load_all_funds_config()
    code_to_cfg = {f["fund_code"]: f for f in funds}

    for code in fund_codes:
        cfg = code_to_cfg.get(code, {"weekly_budget": 200.0, "fixed_ratio": 0.40})
        proxy_code = cfg.get("proxy_index", "?")

        nav_row = query_df(
            "SELECT * FROM nav_daily_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (code,),
        )
        proxy_row = query_df(
            "SELECT date,close,ma200,dev_pct,source FROM proxy_daily_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (code,),
        )

        if len(nav_row) == 0:
            results.append({"fund_code": code, "error": "无净值数据", "risk_guard_passed": False})
            continue

        nav_val = float(nav_row["nav"].iloc[0])
        nav_date = str(nav_row["date"].iloc[0])
        nav_src = str(nav_row["source"].iloc[0]) if "source" in nav_row.columns else "?"

        if len(proxy_row) == 0:
            results.append({
                "fund_code": code, "fund_nav": nav_val,
                "data_source": nav_src, "is_trusted": False,
                "risk_guard_passed": False,
                "risk_guard_errors": ["无代理指数数据"],
            })
            continue

        proxy_close = float(proxy_row["close"].iloc[0])
        proxy_ma200 = float(proxy_row["ma200"].iloc[0])
        dev_pct = float(proxy_row["dev_pct"].iloc[0])
        idx_src = str(proxy_row["source"].iloc[0])
        idx_date = str(proxy_row["date"].iloc[0])

        # 准备金
        state = query_df(
            "SELECT reserve_balance FROM fund_state WHERE fund_code=?",
            (code,),
        )
        reserve_balance = float(state["reserve_balance"].iloc[0]) if len(state) > 0 else 0.0

        # 策略计算
        try:
            plan_result = calc_dca(cfg, reserve_balance, dev_pct)
        except Exception as e:
            results.append({
                "fund_code": code, "error": f"策略计算失败: {e}",
                "risk_guard_passed": False,
            })
            continue

        # risk_guard
        risk = advice_allowed(
            nav=nav_val, proxy_close=proxy_close, ma200=proxy_ma200,
            dev_pct=dev_pct, source=idx_src, plan=plan_result,
            weekly_budget=cfg.get("weekly_budget", 200.0),
        )
        is_trusted = idx_src.lower() != "mock"

        entry = {
            "fund_code": code,
            "fund_nav": nav_val,
            "fund_nav_date": nav_date,
            "proxy_code": proxy_code,
            "proxy_close": proxy_close,
            "proxy_ma200": proxy_ma200,
            "proxy_date": idx_date,
            "dev_pct": dev_pct,
            "data_source": idx_src,
            "is_trusted": is_trusted,
            "risk_guard_passed": risk.passed,
            "risk_guard_errors": risk.errors,
            "fixed_amount": plan_result.fixed_amount,
            "dynamic_amount": plan_result.dynamic_amount,
            "reserve_before": plan_result.reserve_before,
            "reserve_after": plan_result.reserve_after,
        }
        results.append(entry)

    return results


def _dry_run_live() -> list:
    """Live dry-run：调用 sample_and_store_one（可能触发网络请求）。"""
    funds, _ = load_all_funds_config()
    if not funds:
        return []

    results = []
    for cfg in funds:
        code = cfg.get("fund_code", "?")
        proxy_code = cfg.get("proxy_index", "?")
        try:
            r = sample_and_store_one(cfg)
        except Exception as exc:
            results.append({
                "fund_code": code,
                "error": str(exc),
                "risk_guard_passed": False,
            })
            continue

        nav_val = r.get("nav")
        nav_date = r.get("dev", {}).get("date", "?")
        idx_src = r.get("idx_src", "?")
        dev = r.get("dev", {})
        plan = r.get("plan", {})
        rg = r.get("risk_guard", {})
        is_trusted = (idx_src or "").lower() != "mock"

        results.append({
            "fund_code": code,
            "fund_nav": nav_val,
            "fund_nav_date": nav_date,
            "proxy_code": proxy_code,
            "proxy_close": dev.get("current_price"),
            "proxy_ma200": dev.get("ma200"),
            "dev_pct": dev.get("deviation_pct"),
            "data_source": idx_src,
            "is_trusted": is_trusted,
            "risk_guard_passed": rg.get("passed", False),
            "risk_guard_errors": rg.get("errors", []),
            "fixed_amount": plan.get("fixed_amount"),
            "dynamic_amount": plan.get("dynamic_amount"),
            "reserve_before": plan.get("reserve_before"),
            "reserve_after": plan.get("reserve_after"),
        })

    return results


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="CompoundInterestPlan 实盘辅助")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只读取/计算，不写入数据库"
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="（配合 --dry-run）只从数据库读取，不做网络请求"
    )
    parser.add_argument(
        "--format", choices=["json", "table"], default="json",
        help="输出格式 (default: json)"
    )
    args = parser.parse_args()

    if args.dry_run:
        dry_run_all(output_format=args.format, offline=args.offline)
    else:
        print("用法: python -m src.app.services.actions --dry-run [--offline] [--format json|table]")
        print("      只计算不写入。不加 --dry-run 不执行任何操作。")
