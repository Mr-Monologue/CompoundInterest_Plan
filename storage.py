# storage.py
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("trend.db")


@contextmanager
def connect_db():
    con = sqlite3.connect(DB_PATH)
    try:
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
CREATE TABLE IF NOT EXISTS proxy_daily (
  date TEXT PRIMARY KEY,
  close REAL NOT NULL,
  ma200 REAL,
  dev_pct REAL,
  source TEXT
);
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
"""


def init_db():
    with connect_db() as con:
        con.executescript(DDL)
