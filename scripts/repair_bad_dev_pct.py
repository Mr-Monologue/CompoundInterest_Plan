#!/usr/bin/env python3
"""
修复 proxy_daily_v2 和 dca_plan_v2 中的坏 dev_pct 数据。

问题背景：
    旧代码错误地把基金净值传入了 MA200 偏离度计算：
    dev_pct = (fund_nav - proxy_ma200) / proxy_ma200
    正确应为：
    dev_pct = (proxy_close - proxy_ma200) / proxy_ma200

    这导致数据库中 dev_pct 值约为 -99.96% 的 6 条脏数据。

用法：
    python scripts/repair_bad_dev_pct.py           # 列出受影响的记录
    python scripts/repair_bad_dev_pct.py --mark    # 标记为 invalid（不改数据，加 TAG）
    python scripts/repair_bad_dev_pct.py --recalc  # 重新计算 dev_pct
    python scripts/repair_bad_dev_pct.py --dry-run # 只预览不执行
"""

import sys
import os
import argparse
import sqlite3
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DB_PATH = "data/trend.db"

# 坏数据判定：|dev_pct| > 0.5（偏离 > 50%）
BAD_PCT_THRESHOLD = 0.50


def find_bad_rows(con: sqlite3.Connection) -> list:
    """查找所有 dev_pct 异常的记录"""
    rows = con.execute(
        """SELECT rowid, fund_code, date, close, ma200, dev_pct, source
           FROM proxy_daily_v2
           WHERE ABS(dev_pct) > ? OR dev_pct IS NULL
           ORDER BY date""",
        (BAD_PCT_THRESHOLD,),
    ).fetchall()
    return rows


def recalc_dev_pct(close: float, ma200: float) -> float:
    """重新计算正确的 MA200 偏离度"""
    if ma200 <= 0:
        return None
    return (close - ma200) / ma200


def repair_dry_run(con: sqlite3.Connection) -> None:
    """预览模式：只输出，不修改"""
    rows = find_bad_rows(con)
    if not rows:
        print("✅ 未发现坏 dev_pct 数据。")
        return

    print(f"发现 {len(rows)} 条坏 dev_pct 记录：\n")
    print(f"{'RowID':<6} {'fund_code':<10} {'date':<12} {'close':>10} {'ma200':>10} {'old_dev%':>10} {'new_dev%':>10} {'src':<10}")
    print("-" * 80)
    for r in rows:
        rowid, fund_code, date, close, ma200, old_dev, source = r
        new_dev = recalc_dev_pct(close, ma200)
        new_str = f"{new_dev*100:>9.4f}%" if new_dev is not None else "ERROR"
        print(
            f"{rowid:<6} {fund_code:<10} {date:<12} "
            f"{close:>10.2f} {ma200:>10.2f} "
            f"{old_dev*100:>9.4f}% {new_str} "
            f"{source:<10}"
        )


def repair_mark(con: sqlite3.Connection) -> int:
    """标记模式：在 source 字段后追加 [INVALID_BAD_DEV_PCT]"""
    rows = find_bad_rows(con)
    if not rows:
        print("✅ 未发现需要标记的记录。")
        return 0

    count = 0
    for r in rows:
        rowid, fund_code, date, close, ma200, old_dev, source = r
        if "[INVALID_BAD_DEV_PCT]" in (source or ""):
            continue
        new_source = f"{source} [INVALID_BAD_DEV_PCT]"
        con.execute(
            "UPDATE proxy_daily_v2 SET source=? WHERE rowid=?",
            (new_source, rowid),
        )
        # 同时标记对应的 dca_plan_v2
        con.execute(
            """UPDATE dca_plan_v2 SET level='invalid'
               WHERE fund_code=? AND date=? AND ABS(dev_pct) > ?""",
            (fund_code, date, BAD_PCT_THRESHOLD),
        )
        count += 1

    con.commit()
    print(f"✓ 已标记 {count} 条记录（source 字段追加 [INVALID_BAD_DEV_PCT]）。")
    print("  对应的 dca_plan_v2.level 已设为 'invalid'。")
    print("  数据未删除，原始值完整保留。")
    return count


def repair_recalc(con: sqlite3.Connection) -> int:
    """重算模式：重新计算 dev_pct 并更新"""
    rows = find_bad_rows(con)
    if not rows:
        print("✅ 未发现需要重算的记录。")
        return 0

    count = 0
    for r in rows:
        rowid, fund_code, date, close, ma200, old_dev, source = r
        new_dev = recalc_dev_pct(close, ma200)
        if new_dev is None:
            print(f"⚠ 跳过 {fund_code} {date}: ma200={ma200} ≤ 0")
            continue

        # 更新 proxy_daily_v2
        con.execute(
            "UPDATE proxy_daily_v2 SET dev_pct=? WHERE rowid=?",
            (new_dev, rowid),
        )
        # 更新 dca_plan_v2 中的对应 dev_pct
        con.execute(
            "UPDATE dca_plan_v2 SET dev_pct=? WHERE fund_code=? AND date=? AND ABS(dev_pct) > ?",
            (new_dev, fund_code, date, BAD_PCT_THRESHOLD),
        )
        count += 1
        print(f"  {fund_code} {date}: dev_pct {old_dev*100:.2f}% → {new_dev*100:.2f}%")

    con.commit()
    print(f"\n✓ 已重算 {count} 条记录。")
    return count


def main():
    parser = argparse.ArgumentParser(
        description="修复脏 dev_pct 数据（旧 BUG：(fund_nav - ma200) / ma200）"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run", action="store_true",
        help="只预览受影响记录，不做任何修改"
    )
    group.add_argument(
        "--mark", action="store_true",
        help="标记为 invalid（source 追加 [INVALID_BAD_DEV_PCT]）"
    )
    group.add_argument(
        "--recalc", action="store_true",
        help="重新计算正确的 dev_pct = (close - ma200) / ma200"
    )
    args = parser.parse_args()

    con = sqlite3.connect(DB_PATH)
    try:
        if args.mark:
            repair_mark(con)
        elif args.recalc:
            repair_recalc(con)
        else:
            # 默认 dry-run
            print("=== DRY-RUN 模式：只预览，不修改 ===\n")
            repair_dry_run(con)
            print("\n提示：加 --mark 标记脏数据，加 --recalc 自动重算。")
    finally:
        con.close()


if __name__ == "__main__":
    main()
