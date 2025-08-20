# weekly_review.py
from datetime import date, timedelta
import sqlite3, pandas as pd
from storage import connect_db, DB_PATH


def weekly():
    end = pd.to_datetime(date.today())
    start = end - timedelta(days=7)
    with connect_db() as con:
        nav = pd.read_sql("SELECT * FROM nav_daily", con, parse_dates=["date"])
        proxy = pd.read_sql("SELECT * FROM proxy_daily", con, parse_dates=["date"])
        plan = pd.read_sql("SELECT * FROM dca_plan", con, parse_dates=["date"])
        hold = pd.read_sql("SELECT * FROM holdings_snapshot", con, parse_dates=["date"])

    # 截取近 4~12 周窗口，计算环比/同比等指标…
    win = proxy[proxy["date"].between(start, end)].copy()
    # ……略：生成 Markdown 摘要和图片文件（Plotly）


if __name__ == "__main__":
    weekly()
