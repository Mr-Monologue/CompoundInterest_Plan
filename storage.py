# storage.py
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("trend.db")


@contextmanager
def connect_db():
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        yield con
        con.commit()
    finally:
        con.close()


DDL = """
CREATE TABLE IF NOT EXISTS nav_daily (
  date TEXT PRIMARY KEY,
  nav REAL NOT NULL,
  source TEXT
);
CREATE INDEX IF NOT EXISTS idx_nav_daily_date ON nav_daily(date);
CREATE TABLE IF NOT EXISTS proxy_daily (
  date TEXT PRIMARY KEY,
  close REAL NOT NULL,
  ma200 REAL,
  dev_pct REAL,
  source TEXT
);
CREATE INDEX IF NOT EXISTS idx_proxy_daily_date ON proxy_daily(date);
CREATE TABLE IF NOT EXISTS dca_plan (
  date TEXT PRIMARY KEY,
  level TEXT,
  dev_pct REAL,
  base_amt REAL,
  dyn_amt REAL,
  total_amt REAL,
  reserve_before REAL,
  reserve_after REAL
);
CREATE INDEX IF NOT EXISTS idx_dca_plan_date ON dca_plan(date);
CREATE TABLE IF NOT EXISTS holdings_snapshot (
  date TEXT PRIMARY KEY,
  units REAL,
  avg_cost REAL,
  nav REAL,
  mtm REAL,
  unreal_pnl REAL,
  unreal_pct REAL,
  total_pnl REAL
);
CREATE INDEX IF NOT EXISTS idx_holdings_snapshot_date ON holdings_snapshot(date);
"""

DDL_V2 = """
CREATE TABLE IF NOT EXISTS nav_daily_v2 (
  fund_code TEXT NOT NULL,
  date TEXT NOT NULL,
  nav REAL NOT NULL,
  source TEXT,
  timestamp INTEGER,
  PRIMARY KEY (fund_code, date)
);
CREATE TABLE IF NOT EXISTS proxy_daily_v2 (
  fund_code TEXT NOT NULL,
  date TEXT NOT NULL,
  close REAL NOT NULL,
  ma200 REAL,
  dev_pct REAL,
  source TEXT,
  timestamp INTEGER,
  PRIMARY KEY (fund_code, date)
);
CREATE TABLE IF NOT EXISTS dca_plan_v2 (
  fund_code TEXT NOT NULL,
  date TEXT NOT NULL,
  level TEXT,
  dev_pct REAL,
  base_amt REAL,
  dyn_amt REAL,
  total_amt REAL,
  reserve_before REAL,
  reserve_after REAL,
  timestamp INTEGER,
  PRIMARY KEY (fund_code, date)
);
CREATE TABLE IF NOT EXISTS holdings_snapshot_v2 (
  fund_code TEXT NOT NULL,
  date TEXT NOT NULL,
  units REAL,
  avg_cost REAL,
  nav REAL,
  mtm REAL,
  unreal_pnl REAL,
  unreal_pct REAL,
  total_pnl REAL,
  timestamp INTEGER,
  PRIMARY KEY (fund_code, date)
);
CREATE TABLE IF NOT EXISTS fund_state (
  fund_code TEXT PRIMARY KEY,
  reserve_balance REAL DEFAULT 0,
  last_signal_date TEXT,
  last_low_trigger_date TEXT,
  updated_at INTEGER
);
"""


def init_db():
    with connect_db() as con:
        con.executescript(DDL)
        con.executescript(DDL_V2)
        # 检查并添加 timestamp 列到现有表中
        tables = ["nav_daily", "proxy_daily", "dca_plan", "holdings_snapshot"]
        for table in tables:
            result = con.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in result.fetchall()]
            if "timestamp" not in columns:
                try:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN timestamp INTEGER")
                    con.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_{table}_timestamp ON {table}(timestamp)"
                    )
                    con.execute(
                        f"UPDATE {table} SET timestamp = strftime('%s', 'now') WHERE timestamp IS NULL"
                    )
                except Exception as e:
                    print(f"Failed to add timestamp column to {table}: {e}")
        # 一次性迁移脚本：将老数据迁移到 v2 表
        for table in tables:
            v2_table = f"{table}_v2"
            result = con.execute(
                f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{table}'"
            )
            if result.fetchone()[0] > 0:
                result = con.execute(f"SELECT COUNT(*) FROM {table}")
                if result.fetchone()[0] > 0:
                    columns = [
                        row[1] for row in con.execute(f"PRAGMA table_info({table})")
                    ]
                    columns_str = ", ".join(columns)
                    con.execute(
                        f"INSERT OR IGNORE INTO {v2_table} (fund_code, {columns_str}) SELECT '000083', {columns_str} FROM {table}"
                    )
                    print(f"Migrated data from {table} to {v2_table}")
