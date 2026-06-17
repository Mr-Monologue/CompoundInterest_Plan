#!/usr/bin/env python3
"""
修复历史 level 字段 — 基于 classify_dev_pct 重算。

问题: 旧数据 level="invalid" 或与 dev_pct 不匹配。
解决: 对每条记录调用 classify_dev_pct(dev_pct) 重算 level。

用法:
    python scripts/repair_level_from_dev_pct.py --dry-run   # 预览
    python scripts/repair_level_from_dev_pct.py --apply      # 执行修复

安全:
    - 执行前自动备份数据库
    - 不 DROP TABLE
    - 记录修复日志到 reports/repair/
"""

import sys
import os
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.app.core.strategy import classify_dev_pct

DB_PATH = Path("data/trend.db")
REPAIR_LOG = Path("reports/repair")

TABLES_TO_FIX = ["dca_plan_v2"]  # tables with level + dev_pct columns


def backup_db() -> str:
    """Safe backup before repair."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = Path(f"data/trend.db.before_level_repair_{ts}")
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(backup_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    print(f"✓ 备份: {backup_path} ({backup_path.stat().st_size:,} bytes)")
    return str(backup_path)


def find_mismatches(con: sqlite3.Connection) -> list:
    """Find rows where stored level != classify_dev_pct(dev_pct)."""
    mismatches = []
    for table in TABLES_TO_FIX:
        try:
            rows = con.execute(
                f"SELECT rowid, fund_code, date, level, dev_pct FROM {table} WHERE dev_pct IS NOT NULL ORDER BY date"
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        for r in rows:
            rowid, code, dt, stored, dev = r
            expected = classify_dev_pct(dev)
            if stored != expected:
                mismatches.append((table, rowid, code, dt, stored, dev, expected))
    return mismatches


def dry_run(con: sqlite3.Connection):
    mismatches = find_mismatches(con)
    if not mismatches:
        print("✅ 未发现 level 不匹配的记录。")
        return

    print(f"发现 {len(mismatches)} 条不匹配记录：\n")
    print(f"{'Table':<20} {'rowid':<6} {'Date':<12} {'stored':<10} {'dev_pct':>10} {'expected':<10}")
    print("-" * 70)
    for table, rowid, code, dt, stored, dev, expected in mismatches:
        print(f"{table:<20} {rowid:<6} {dt:<12} {stored:<10} {dev*100:>9.2f}% {expected:<10}")
    print(f"\n提示: python scripts/repair_level_from_dev_pct.py --apply")


def apply_fix(con: sqlite3.Connection):
    mismatches = find_mismatches(con)
    if not mismatches:
        print("✅ 未发现需要修复的记录。")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    REPAIR_LOG.mkdir(parents=True, exist_ok=True)
    log_path = REPAIR_LOG / f"level_repair_{today}.md"

    lines = [
        f"# Level 修复日志 — {today}",
        f"执行时间: {datetime.now().isoformat()}",
        "",
        "## 修复记录",
        "",
        "| Table | rowid | Date | stored | dev_pct | corrected |",
        "|-------|-------|------|--------|---------|-----------|",
    ]

    count = 0
    for table, rowid, code, dt, stored, dev, expected in mismatches:
        con.execute(f"UPDATE {table} SET level=? WHERE rowid=?", (expected, rowid))
        count += 1
        lines.append(
            f"| {table} | {rowid} | {dt} | {stored} | {dev*100:.2f}% | {expected} |"
        )

    con.commit()
    lines.append("")
    lines.append(f"## 总计: {count} 条记录已修复")
    log_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"✓ 已修复 {count} 条记录")
    print(f"  日志: {log_path}")


def main():
    parser = argparse.ArgumentParser(description="修复历史 level 字段")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="只预览")
    group.add_argument("--apply", action="store_true", help="执行修复")
    args = parser.parse_args()

    con = sqlite3.connect(str(DB_PATH))
    try:
        if args.dry_run:
            dry_run(con)
        else:
            backup_db()
            apply_fix(con)
    finally:
        con.close()


if __name__ == "__main__":
    main()
