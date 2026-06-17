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

        # Migrate transaction: add fee column if missing
        if "transaction" in tables:
            cols = [c["name"] for c in inspector.get_columns("transaction")]
            if "fee" not in cols:
                with engine.connect() as conn:
                    conn.execute(text('ALTER TABLE "transaction" ADD COLUMN fee FLOAT DEFAULT 0.0'))
                    conn.commit()

        # Migrate planstate: add missing columns
        if "planstate" in tables:
            cols = [c["name"] for c in inspector.get_columns("planstate")]
            with engine.connect() as conn:
                if "pool_balance" not in cols:
                    conn.execute(text("ALTER TABLE planstate ADD COLUMN pool_balance FLOAT DEFAULT 0.0"))
                if "base_investment" not in cols:
                    conn.execute(text("ALTER TABLE planstate ADD COLUMN base_investment FLOAT DEFAULT 200.0"))
                conn.commit()

        # Migrate asset: add max_weight_limit
        if "asset" in tables:
            cols = [c["name"] for c in inspector.get_columns("asset")]
            if "max_weight_limit" not in cols:
                with engine.connect() as conn:
                    conn.execute(text("ALTER TABLE asset ADD COLUMN max_weight_limit FLOAT DEFAULT 0.2"))
                    conn.commit()

        # Migrate dailyplan: add grid_pos, created_by, idempotency_key
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

    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
