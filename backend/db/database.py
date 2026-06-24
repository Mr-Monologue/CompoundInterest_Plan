from sqlmodel import SQLModel, create_engine, Session
import os

DB_PATH = os.environ.get("COMPOUND_DB_PATH")
if not DB_PATH:
    p = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH = os.path.join(p, "invest.db")

sqlite_file_name = DB_PATH
sqlite_url = f"sqlite:///{DB_PATH}"
engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    """初始化 — 不自动建表，只做迁移"""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if not tables:
        return  # No tables — don't auto-create, let health report DEGRADED
    if "dailyplan" in tables:
        cols = [c["name"] for c in inspector.get_columns("dailyplan")]
        with engine.connect() as conn:
            if "grid_pos" not in cols:
                conn.execute(text("ALTER TABLE dailyplan ADD COLUMN grid_pos FLOAT DEFAULT 0.0"))
            conn.commit()
    if "dailydecision" in tables:
        cols = [c["name"] for c in inspector.get_columns("dailydecision")]
        with engine.connect() as conn:
            if "candidate_amount" not in cols:
                conn.execute(text("ALTER TABLE dailydecision ADD COLUMN candidate_amount FLOAT"))
            if "downgrade_reason" not in cols:
                conn.execute(text("ALTER TABLE dailydecision ADD COLUMN downgrade_reason TEXT DEFAULT ''"))
            conn.commit()
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session