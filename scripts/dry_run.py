#!/usr/bin/env python3
"""
独立 dry-run 入口 — 不触发 data_sources.py 的模块级副作用。
用法: python scripts/dry_run.py [--format json|table]
"""

import sys
import os
import json
import argparse

# 确保项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 仅导入无副作用模块
from src.app.db.storage import query_df, connect_db
from src.app.core.config import load_all_funds_config
from src.app.core.risk_guard import advice_allowed
from src.app.core.strategy import calculate_dca_allocation as calc_dca


def dry_run_offline(format: str = "json"):
    funds, _ = load_all_funds_config()
    code_to_cfg = {f["fund_code"]: f for f in funds}

    with connect_db() as con:
        fund_codes = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT fund_code FROM nav_daily_v2 ORDER BY fund_code"
            ).fetchall()
        ]

    results = []
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
            results.append(
                {"fund_code": code, "error": "无净值数据", "risk_guard_passed": False}
            )
            continue

        nav_val = float(nav_row["nav"].iloc[0])
        nav_date = str(nav_row["date"].iloc[0])
        nav_src = str(nav_row["source"].iloc[0]) if "source" in nav_row.columns else "?"

        if len(proxy_row) == 0:
            results.append(
                {
                    "fund_code": code,
                    "fund_nav": nav_val,
                    "data_source": nav_src,
                    "is_trusted": False,
                    "risk_guard_passed": False,
                    "risk_guard_errors": ["无代理指数数据"],
                }
            )
            continue

        proxy_close = float(proxy_row["close"].iloc[0])
        proxy_ma200 = float(proxy_row["ma200"].iloc[0])
        dev_pct = float(proxy_row["dev_pct"].iloc[0])
        idx_src = str(proxy_row["source"].iloc[0])
        idx_date = str(proxy_row["date"].iloc[0])

        state = query_df(
            "SELECT reserve_balance FROM fund_state WHERE fund_code=?", (code,)
        )
        reserve_balance = (
            float(state["reserve_balance"].iloc[0]) if len(state) > 0 else 0.0
        )

        try:
            plan_result = calc_dca(cfg, reserve_balance, dev_pct)
        except Exception as e:
            results.append(
                {
                    "fund_code": code,
                    "error": f"策略计算失败: {e}",
                    "risk_guard_passed": False,
                }
            )
            continue

        risk = advice_allowed(
            nav=nav_val,
            proxy_close=proxy_close,
            ma200=proxy_ma200,
            dev_pct=dev_pct,
            source=idx_src,
            plan=plan_result,
            weekly_budget=cfg.get("weekly_budget", 200.0),
        )
        is_trusted = idx_src.lower() != "mock"

        results.append(
            {
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
        )

    if format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    elif format == "table":
        header = f"{'Code':<8} {'NAV':>8} {'Dev%':>8} {'Trusted':>8} {'Guard':>8} {'Fixed':>8} {'Dyn':>8} {'Reserve':>8}"
        print(header)
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CompoundInterestPlan dry-run")
    parser.add_argument(
        "--format", choices=["json", "table"], default="json", help="输出格式"
    )
    args = parser.parse_args()
    dry_run_offline(format=args.format)
