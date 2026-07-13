"""v2.1 Safe Migration — add Asset fields + new Weekly Plan tables."""
import sqlite3, shutil, os
from pathlib import Path
from datetime import datetime


def migrate(db_path: str):
    """Run v2.1 migration. Never drops data. Idempotent."""
    db = Path(db_path)
    if not db.exists():
        return {"ok": False, "error": "Database not found"}

    # Backup
    backup = db.parent / f"invest_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(db, backup)

    conn = sqlite3.connect(str(db))
    cursor = conn.cursor()

    # Check existing columns on Asset
    cursor.execute("PRAGMA table_info(asset)")
    cols = {row[1] for row in cursor.fetchall()}

    v21_fields = [
        ("role", "TEXT DEFAULT 'core'"),
        ("proxy_code", "TEXT"),
        ("proxy_type", "TEXT DEFAULT 'INDEX'"),
        ("theme", "TEXT DEFAULT ''"),
        ("target_weight", "REAL DEFAULT 0.0"),
        ("investment_thesis", "TEXT DEFAULT ''"),
        ("expected_holding_months", "INTEGER DEFAULT 12"),
        ("review_cycle", "TEXT DEFAULT 'quarterly'"),
        ("invalidation_conditions", "TEXT DEFAULT ''"),
        ("enabled", "INTEGER DEFAULT 1"),
    ]

    for name, typ in v21_fields:
        if name not in cols:
            cursor.execute(f"ALTER TABLE asset ADD COLUMN {name} {typ}")

    # Create new tables if not exist
    new_tables = {
        "investment_plan_config": """
            CREATE TABLE IF NOT EXISTS investment_plan_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT DEFAULT 'default',
                weekly_budget REAL DEFAULT 200.0,
                core_target_ratio REAL DEFAULT 0.65,
                satellite_target_ratio REAL DEFAULT 0.35,
                reserve_balance REAL DEFAULT 0.0,
                strategy_version TEXT DEFAULT 'v2.1',
                enabled INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            )
        """,
        "weekly_investment_plan": """
            CREATE TABLE IF NOT EXISTS weekly_investment_plan (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT DEFAULT '',
                week_end TEXT DEFAULT '',
                config_id INTEGER DEFAULT 0,
                strategy_version TEXT DEFAULT 'v2.1',
                status TEXT DEFAULT 'DRAFT',
                available_budget REAL DEFAULT 0.0,
                core_budget REAL DEFAULT 0.0,
                satellite_budget REAL DEFAULT 0.0,
                data_quality_status TEXT DEFAULT 'unknown',
                exposure_status TEXT DEFAULT 'unknown',
                created_at TEXT,
                frozen_at TEXT
            )
        """,
        "weekly_plan_item": """
            CREATE TABLE IF NOT EXISTS weekly_plan_item (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                weekly_plan_id INTEGER DEFAULT 0,
                asset_code TEXT DEFAULT '',
                asset_role TEXT DEFAULT 'core',
                daily_decision_id INTEGER,
                fixed_amount REAL,
                dynamic_amount REAL,
                candidate_amount REAL,
                final_amount REAL,
                action TEXT DEFAULT 'NO_ACTION',
                valuation_state TEXT DEFAULT 'unknown',
                risk_status TEXT DEFAULT 'ok',
                data_quality_status TEXT DEFAULT 'unknown',
                reason_summary TEXT DEFAULT '',
                calculation_trace TEXT DEFAULT '{}',
                created_at TEXT
            )
        """,
        "decision_journal_entry": """
            CREATE TABLE IF NOT EXISTS decision_journal_entry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                weekly_plan_item_id INTEGER,
                created_at TEXT,
                investment_thesis_snapshot TEXT DEFAULT '',
                expected_scenario TEXT DEFAULT '',
                invalidation_conditions TEXT DEFAULT '',
                known_unknowns TEXT DEFAULT '',
                user_note TEXT DEFAULT '',
                immutable INTEGER DEFAULT 1
            )
        """,
    }

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = {row[0] for row in cursor.fetchall()}

    for name, sql in new_tables.items():
        if name not in existing_tables:
            cursor.executescript(sql)

    # Create default config if none exists
    cursor.execute("SELECT COUNT(*) FROM investment_plan_config")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO investment_plan_config (name, weekly_budget, core_target_ratio, satellite_target_ratio,
                                                strategy_version, created_at, updated_at)
            VALUES ('default', 200.0, 0.65, 0.35, 'v2.1', ?, ?)
        """, (datetime.now().isoformat(), datetime.now().isoformat()))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "version": "v2.1",
        "backup": str(backup),
        "asset_fields_added": [n for n, _ in v21_fields if n not in cols],
        "new_tables_created": [n for n in new_tables if n not in existing_tables],
        "default_config_created": True,
    }


if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else "F:/compound-interest-plan/invest.db"
    result = migrate(db)
    print(result)
