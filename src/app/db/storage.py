# storage.py
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("data/trend.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)  # 确保父目录存在


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
CREATE INDEX IF NOT EXISTS idx_nav_daily_v2_fund_date ON nav_daily_v2(fund_code, date);
CREATE INDEX IF NOT EXISTS idx_nav_daily_v2_timestamp ON nav_daily_v2(timestamp);

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
CREATE INDEX IF NOT EXISTS idx_proxy_daily_v2_fund_date ON proxy_daily_v2(fund_code, date);
CREATE INDEX IF NOT EXISTS idx_proxy_daily_v2_timestamp ON proxy_daily_v2(timestamp);

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
CREATE INDEX IF NOT EXISTS idx_dca_plan_v2_fund_date ON dca_plan_v2(fund_code, date);
CREATE INDEX IF NOT EXISTS idx_dca_plan_v2_timestamp ON dca_plan_v2(timestamp);

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
CREATE INDEX IF NOT EXISTS idx_holdings_snapshot_v2_fund_date ON holdings_snapshot_v2(fund_code, date);
CREATE INDEX IF NOT EXISTS idx_holdings_snapshot_v2_timestamp ON holdings_snapshot_v2(timestamp);

CREATE TABLE IF NOT EXISTS fund_state (
  fund_code TEXT PRIMARY KEY,
  reserve_balance REAL DEFAULT 0,
  last_signal_date TEXT,
  last_low_trigger_date TEXT,
  updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_fund_state_updated_at ON fund_state(updated_at);
"""


def init_db():
    """初始化数据库，只创建 v2 表结构"""
    with connect_db() as con:
        # 只创建 v2 表
        con.executescript(DDL_V2)

        # 一次性迁移脚本：将老数据迁移到 v2 表（如果存在老表）
        old_tables = ["nav_daily", "proxy_daily", "dca_plan", "holdings_snapshot"]
        for table in old_tables:
            v2_table = f"{table}_v2"

            # 检查老表是否存在且有数据
            result = con.execute(
                f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='{table}'"
            )
            if result.fetchone()[0] > 0:
                result = con.execute(f"SELECT COUNT(*) FROM {table}")
                if result.fetchone()[0] > 0:
                    # 获取老表的列信息
                    columns = [
                        row[1] for row in con.execute(f"PRAGMA table_info({table})")
                    ]
                    columns_str = ", ".join(columns)

                    # 迁移数据到 v2 表（使用默认基金代码 '000083'）
                    con.execute(
                        f"INSERT OR IGNORE INTO {v2_table} (fund_code, {columns_str}, timestamp) "
                        f"SELECT '000083', {columns_str}, strftime('%s', 'now') FROM {table}"
                    )
                    print(f"✓ 已迁移数据: {table} → {v2_table}")

        print("✓ 数据库初始化完成")


def get_latest_data_for_fund(fund_code: str) -> dict:
    """获取指定基金的最新数据"""
    with connect_db() as con:
        result = {}

        # 获取最新净值
        nav_row = con.execute(
            "SELECT * FROM nav_daily_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (fund_code,),
        ).fetchone()
        if nav_row:
            result["nav"] = {
                "value": nav_row[2],
                "source": nav_row[3],
                "date": nav_row[1],
                "timestamp": nav_row[4],
            }

        # 获取最新指数数据
        proxy_row = con.execute(
            "SELECT * FROM proxy_daily_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (fund_code,),
        ).fetchone()
        if proxy_row:
            result["proxy"] = {
                "close": proxy_row[2],
                "ma200": proxy_row[3],
                "dev_pct": proxy_row[4],
                "source": proxy_row[5],
                "date": proxy_row[1],
                "timestamp": proxy_row[6],
            }

        # 获取最新定投计划
        plan_row = con.execute(
            "SELECT * FROM dca_plan_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (fund_code,),
        ).fetchone()
        if plan_row:
            result["plan"] = {
                "level": plan_row[2],
                "dev_pct": plan_row[3],
                "base_amt": plan_row[4],
                "dyn_amt": plan_row[5],
                "total_amt": plan_row[6],
                "reserve_before": plan_row[7],
                "reserve_after": plan_row[8],
                "date": plan_row[1],
                "timestamp": plan_row[9],
            }

        # 获取最新持仓
        holdings_row = con.execute(
            "SELECT * FROM holdings_snapshot_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (fund_code,),
        ).fetchone()
        if holdings_row:
            result["holdings"] = {
                "units": holdings_row[2],
                "avg_cost": holdings_row[3],
                "nav": holdings_row[4],
                "mtm": holdings_row[5],
                "unreal_pnl": holdings_row[6],
                "unreal_pct": holdings_row[7],
                "total_pnl": holdings_row[8],
                "date": holdings_row[1],
                "timestamp": holdings_row[9],
            }

        # 获取基金状态
        state_row = con.execute(
            "SELECT * FROM fund_state WHERE fund_code=?", (fund_code,)
        ).fetchone()
        if state_row:
            result["state"] = {
                "reserve_balance": state_row[1],
                "last_signal_date": state_row[2],
                "last_low_trigger_date": state_row[3],
                "updated_at": state_row[4],
            }

        return result


def get_historical_data_for_fund(
    fund_code: str, table_name: str, limit: int = None
) -> list:
    """获取指定基金的历史数据"""
    with connect_db() as con:
        query = f"SELECT * FROM {table_name} WHERE fund_code=? ORDER BY date DESC"
        if limit:
            query += f" LIMIT {limit}"

        rows = con.execute(query, (fund_code,)).fetchall()
        return rows


def get_all_funds_latest_data() -> dict:
    """获取所有基金的最新数据"""
    with connect_db() as con:
        # 获取所有基金代码
        fund_codes = con.execute(
            "SELECT DISTINCT fund_code FROM nav_daily_v2 ORDER BY fund_code"
        ).fetchall()

        result = {}
        for (fund_code,) in fund_codes:
            result[fund_code] = get_latest_data_for_fund(fund_code)

        return result


def clear_old_data(days_to_keep: int = 365):
    """清理旧数据，保留指定天数"""
    with connect_db() as con:
        cutoff_date = f"date('now', '-{days_to_keep} days')"

        tables = [
            "nav_daily_v2",
            "proxy_daily_v2",
            "dca_plan_v2",
            "holdings_snapshot_v2",
        ]
        for table in tables:
            deleted = con.execute(
                f"DELETE FROM {table} WHERE date < {cutoff_date}"
            ).rowcount
            if deleted > 0:
                print(f"✓ 清理 {table}: 删除了 {deleted} 条旧数据")

        con.commit()


def query_df(query: str, params: tuple = None):
    """执行查询并返回 DataFrame"""
    import pandas as pd

    with connect_db() as con:
        if params:
            return pd.read_sql(query, con, params=params)
        else:
            return pd.read_sql(query, con)
