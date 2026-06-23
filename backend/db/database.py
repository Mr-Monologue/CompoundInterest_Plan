from sqlmodel import SQLModel, create_engine, Session
import os

sqlite_file_name = "invest.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=False)


def create_db_and_tables():
    """初始化数据库 — 绝不 DROP TABLE，只用 ALTER TABLE ADD COLUMN"""
    if os.path.exists(sqlite_file_name):
        from sqlalchemy import inspect, text
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        if "transaction" in tables:
            cols = [c["name"] for c in inspector.get_columns("transaction")]
            if "fee" not in cols:
                with engine.connect() as conn:
                    conn.execute(text('ALTER TABLE "transaction" ADD COLUMN fee FLOAT DEFAULT 0.0'))
                    conn.commit()

        if "planstate" in tables:
            cols = [c["name"] for c in inspector.get_columns("planstate")]
            with engine.connect() as conn:
                if "pool_balance" not in cols:
                    conn.execute(text("ALTER TABLE planstate ADD COLUMN pool_balance FLOAT DEFAULT 0.0"))
                if "base_investment" not in cols:
                    conn.execute(text("ALTER TABLE planstate ADD COLUMN base_investment FLOAT DEFAULT 200.0"))
                conn.commit()

        if "asset" in tables:
            cols = [c["name"] for c in inspector.get_columns("asset")]
            if "max_weight_limit" not in cols:
                with engine.connect() as conn:
                    conn.execute(text("ALTER TABLE asset ADD COLUMN max_weight_limit FLOAT DEFAULT 0.2"))
                    conn.commit()

        if "dailyplan" in tables:
            cols = [c["name"] for c in inspector.get_columns("dailyplan")]
            with engine.connect() as conn:
                if "grid_pos" not in cols:
                    conn.execute(text("ALTER TABLE dailyplan ADD COLUMN grid_pos FLOAT DEFAULT 0.0"))
                if "created_by" not in cols:
                    conn.execute(text("ALTER TABLE dailyplan ADD COLUMN created_by TEXT DEFAULT 'scheduler'"))
                if "idempotency_key" not in cols:
                    conn.execute(text("ALTER TABLE dailyplan ADD COLUMN idempotency_key TEXT"))
                conn.commit()

        # v0.8.3/v0.8.4: DailyDecision + UserDecision new columns
        if "dailydecision" in tables:
            cols = [c["name"] for c in inspector.get_columns("dailydecision")]
            new_cols = [
                ("candidate_amount", "FLOAT"), ("final_amount", "FLOAT"),
                ("amount_source", "TEXT DEFAULT 'strategy'"), ("exposure_status", "TEXT DEFAULT 'PASS'"),
                ("exposure_reasons", "TEXT DEFAULT ''"), ("theme_bucket", "TEXT DEFAULT '未分类'"),
                ("downgraded_from_action", "TEXT DEFAULT ''"), ("downgrade_reason", "TEXT DEFAULT ''"),
                ("downgrade_from_fund", "TEXT DEFAULT ''"), ("candidate_action", "TEXT DEFAULT ''"),
                ("final_action", "TEXT DEFAULT ''"), ("exposure_guard_applied", "INTEGER DEFAULT 0"),
                ("industry_exposure_before", "TEXT DEFAULT ''"), ("classification_source", "TEXT DEFAULT ''"),
                ("classification_confidence", "TEXT DEFAULT ''"), ("holding_date", "TEXT DEFAULT ''"),
                ("stale_holdings_warning", "INTEGER DEFAULT 0"),
            ]
            with engine.connect() as conn:
                for col_name, col_type in new_cols:
                    if col_name not in cols:
                        conn.execute(text(f"ALTER TABLE dailydecision ADD COLUMN {col_name} {col_type}"))
                conn.commit()

        if "userdecision" in tables:
            cols = [c["name"] for c in inspector.get_columns("userdecision")]
            with engine.connect() as conn:
                if "override_exposure_guard" not in cols:
                    conn.execute(text("ALTER TABLE userdecision ADD COLUMN override_exposure_guard INTEGER DEFAULT 0"))
                if "override_reason" not in cols:
                    conn.execute(text("ALTER TABLE userdecision ADD COLUMN override_reason TEXT DEFAULT ''"))
                conn.commit()

    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
