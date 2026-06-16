#!/usr/bin/env python3
"""
数据库安全备份脚本

用法:
    python scripts/backup_db.py                  # 备份到 data/
    python scripts/backup_db.py --output /path/  # 指定输出目录

使用 sqlite3 backup API，不阻塞读写。
"""

import sys
import os
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

DB_PATH = Path("data/trend.db")


def backup_db(output_dir: str = "data") -> str:
    """备份数据库，返回备份文件路径"""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"数据库不存在: {DB_PATH}")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = out / f"trend.db.backup_{ts}"

    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(backup_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    size = backup_path.stat().st_size
    print(f"✓ 备份完成: {backup_path} ({size:,} bytes)")
    return str(backup_path)


def list_backups(output_dir: str = "data") -> list:
    """列出所有备份"""
    out = Path(output_dir)
    if not out.exists():
        return []
    return sorted(out.glob("trend.db.backup_*"), key=lambda p: p.stat().st_mtime, reverse=True)


def main():
    parser = argparse.ArgumentParser(description="CompoundInterestPlan 数据库备份")
    parser.add_argument("--output", default="data", help="输出目录 (default: data)")
    parser.add_argument("--list", action="store_true", help="列出已有备份")
    args = parser.parse_args()

    if args.list:
        backups = list_backups(args.output)
        if backups:
            print(f"已有 {len(backups)} 个备份:")
            for b in backups:
                print(f"  {b.name} ({b.stat().st_size:,} bytes)")
        else:
            print("暂无备份。")
        return

    backup_db(args.output)


if __name__ == "__main__":
    main()
