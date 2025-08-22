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


def init_db():
    with connect_db() as con:
        con.executescript(DDL)
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
