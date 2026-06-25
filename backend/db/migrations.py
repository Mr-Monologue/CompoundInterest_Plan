"""migrations.py — formal schema migrations for invest.db."""
import sqlite3, os, shutil
from datetime import datetime

DB_PATH = os.environ.get("COMPOUND_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "invest.db"))

MIGRATIONS = [
    {
        "version": "20260625_001",
        "name": "add_dailydecision_decision_source",
        "sql": "ALTER TABLE dailydecision ADD COLUMN decision_source TEXT DEFAULT 'manual'",
        "check": lambda c: "decision_source" in [r[1] for r in c.execute("PRAGMA table_info(dailydecision)").fetchall()],
        "table": "dailydecision",
    },
    {
        "version": "20260625_002",
        "name": "add_dailydecision_classification_fields",
        "sql": [
            "ALTER TABLE dailydecision ADD COLUMN classification_source TEXT DEFAULT ''",
            "ALTER TABLE dailydecision ADD COLUMN classification_confidence TEXT DEFAULT ''",
        ],
        "check": lambda c: "classification_source" in [r[1] for r in c.execute("PRAGMA table_info(dailydecision)").fetchall()],
        "table": "dailydecision",
    },
]


def ensure_migrations_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT UNIQUE,
            name TEXT,
            applied_at TEXT,
            success INTEGER,
            error TEXT,
            git_commit TEXT
        )
    """)
    conn.commit()


def backup_db():
    bak = f"{DB_PATH}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB_PATH, bak)
    return bak


def run_migrations():
    conn = sqlite3.connect(DB_PATH)
    ensure_migrations_table(conn)
    applied = [r[0] for r in conn.execute("SELECT version FROM schema_migrations WHERE success=1").fetchall()]
    results = []
    for m in MIGRATIONS:
        if m["version"] in applied:
            results.append({"version": m["version"], "status": "skipped", "reason": "already applied"})
            continue
        if m["table"] not in [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
            results.append({"version": m["version"], "status": "skipped", "reason": f"table {m['table']} not found"})
            continue
        if m.get("check") and m["check"](conn):
            conn.execute("INSERT INTO schema_migrations(version,name,applied_at,success) VALUES(?,?,?,?)",
                         [m["version"], m["name"], datetime.now().isoformat(), 1])
            conn.commit()
            results.append({"version": m["version"], "status": "already_detected"})
            continue
        try:
            sqls = m["sql"] if isinstance(m["sql"], list) else [m["sql"]]
            for sql in sqls:
                conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations(version,name,applied_at,success) VALUES(?,?,?,?)",
                         [m["version"], m["name"], datetime.now().isoformat(), 1])
            conn.commit()
            results.append({"version": m["version"], "status": "applied"})
        except Exception as e:
            conn.execute("INSERT INTO schema_migrations(version,name,applied_at,success,error) VALUES(?,?,?,?,?)",
                         [m["version"], m["name"], datetime.now().isoformat(), 0, str(e)[:200]])
            conn.commit()
            results.append({"version": m["version"], "status": "failed", "error": str(e)[:200]})
    conn.close()
    return results


def check_schema():
    conn = sqlite3.connect(DB_PATH)
    missing = []
    for m in MIGRATIONS:
        if m.get("check") and not m["check"](conn):
            missing.append(f"{m['table']}.{m['name'].split('add_')[-1] if 'add_' in m['name'] else m['name']}")
    conn.close()
    return not bool(missing), missing


if __name__ == "__main__":
    bak = backup_db()
    print(f"Backup: {bak}")
    results = run_migrations()
    for r in results:
        print(f"  {r['version']}: {r['status']}")
    ok, missing = check_schema()
    print(f"Schema ready: {ok}, missing: {missing}")
