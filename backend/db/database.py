from sqlmodel import SQLModel, create_engine, Session
import os

# ABSOLUTE path only — env var or project-root/invest.db
DB_PATH = os.environ.get("COMPOUND_DB_PATH")
if not DB_PATH:
    p = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH = os.path.join(p, "invest.db")

sqlite_file_name = DB_PATH
sqlite_url = f"sqlite:///{DB_PATH}"
engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"DB_NOT_FOUND: {DB_PATH} — set COMPOUND_DB_PATH or restore invest.db")
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if "dailyplan" in tables:
        cols = [c["name"] for c in inspector.get_columns("dailyplan")]
        with engine.connect() as conn:
            if "grid_pos" not in cols:
                conn.execute(text("ALTER TABLE dailyplan ADD COLUMN grid_pos FLOAT DEFAULT 0.0"))
            if "created_by" not in cols:
                conn.execute(text("ALTER TABLE dailyplan ADD COLUMN created_by TEXT DEFAULT 'scheduler'"))
            conn.commit()
    if "dailydecision" in tables:
        cols = [c["name"] for c in inspector.get_columns("dailydecision")]
        for col_name, col_type in [("candidate_amount","FLOAT"),("downgrade_reason","TEXT DEFAULT ''")]:
            if col_name not in cols:
                with engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE dailydecision ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
