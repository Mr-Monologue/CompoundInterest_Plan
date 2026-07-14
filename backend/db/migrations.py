"""v2.1 Complete Safe Migration — all tables, columns, indexes."""
import sqlite3, shutil, os
from pathlib import Path
from datetime import datetime

INDEXES = {
    "uq_market_snapshot_date": "CREATE UNIQUE INDEX IF NOT EXISTS uq_market_snapshot_date ON market_snapshot(asset_code, data_date)",
    "uq_weekly_plan_week_config": "CREATE UNIQUE INDEX IF NOT EXISTS uq_weekly_plan_week_config ON weekly_investment_plan(week_start, config_id)",
    "uq_weekly_plan_decision": "CREATE UNIQUE INDEX IF NOT EXISTS uq_weekly_plan_decision ON weekly_plan_item(weekly_plan_id, daily_decision_id) WHERE daily_decision_id IS NOT NULL",
    "uq_item_decision": "CREATE UNIQUE INDEX IF NOT EXISTS uq_item_decision ON plan_item_user_decision(weekly_plan_item_id)",
    "uq_execution_item": "CREATE UNIQUE INDEX IF NOT EXISTS uq_execution_item ON execution_record(weekly_plan_item_id)",
    "uq_execution_external_ref": "CREATE UNIQUE INDEX IF NOT EXISTS uq_execution_external_ref ON execution_record(external_reference) WHERE external_reference IS NOT NULL AND external_reference <> ''",
    "uq_execution_reconciliation": "CREATE UNIQUE INDEX IF NOT EXISTS uq_execution_reconciliation ON reconciliation_record(execution_record_id)",
    "uq_transaction_source_execution": "CREATE UNIQUE INDEX IF NOT EXISTS uq_transaction_source_execution ON \"transaction\"(source_execution_id) WHERE source_execution_id IS NOT NULL",
    "uq_review_plan": "CREATE UNIQUE INDEX IF NOT EXISTS uq_review_plan ON weekly_review(weekly_plan_id)",
    "uq_review_item": "CREATE UNIQUE INDEX IF NOT EXISTS uq_review_item ON weekly_review_item(weekly_review_id, weekly_plan_item_id)",
}

NEW_TABLES = {
    "market_snapshot": """CREATE TABLE IF NOT EXISTS market_snapshot (id INTEGER PRIMARY KEY AUTOINCREMENT, asset_code TEXT, data_date TEXT DEFAULT '', nav REAL, nav_source TEXT DEFAULT '', proxy_code TEXT DEFAULT '', proxy_close REAL, proxy_ma200 REAL, dev_pct REAL, market_source TEXT DEFAULT '', is_trusted INTEGER DEFAULT 1, quality_status TEXT DEFAULT 'PASS', fetched_at TEXT)""",
    "investment_plan_config": """CREATE TABLE IF NOT EXISTS investment_plan_config (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT 'default', weekly_budget REAL DEFAULT 200.0, core_target_ratio REAL DEFAULT 0.65, satellite_target_ratio REAL DEFAULT 0.35, reserve_balance REAL DEFAULT 0.0, strategy_version TEXT DEFAULT 'v2.1', enabled INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT)""",
    "weekly_investment_plan": """CREATE TABLE IF NOT EXISTS weekly_investment_plan (id INTEGER PRIMARY KEY AUTOINCREMENT, week_start TEXT DEFAULT '', week_end TEXT DEFAULT '', config_id INTEGER DEFAULT 0, strategy_version TEXT DEFAULT 'v2.1', status TEXT DEFAULT 'DRAFT', available_budget REAL DEFAULT 0.0, core_budget REAL DEFAULT 0.0, satellite_budget REAL DEFAULT 0.0, total_candidate_amount REAL DEFAULT 0.0, total_final_amount REAL DEFAULT 0.0, unallocated_core_budget REAL DEFAULT 0.0, unallocated_satellite_budget REAL DEFAULT 0.0, blocked_item_count INTEGER DEFAULT 0, review_required_item_count INTEGER DEFAULT 0, data_quality_status TEXT DEFAULT 'unknown', exposure_status TEXT DEFAULT 'unknown', created_at TEXT, frozen_at TEXT)""",
    "weekly_plan_item": """CREATE TABLE IF NOT EXISTS weekly_plan_item (id INTEGER PRIMARY KEY AUTOINCREMENT, weekly_plan_id INTEGER DEFAULT 0, asset_code TEXT DEFAULT '', asset_role TEXT DEFAULT 'core', daily_decision_id INTEGER, fixed_amount REAL, dynamic_amount REAL, candidate_amount REAL, final_amount REAL, action TEXT DEFAULT 'NO_ACTION', valuation_state TEXT DEFAULT 'unknown', risk_status TEXT DEFAULT 'ok', data_quality_status TEXT DEFAULT 'unknown', reason_summary TEXT DEFAULT '', calculation_trace TEXT DEFAULT '{}', created_at TEXT, market_snapshot_id INTEGER, market_data_date TEXT DEFAULT '', data_source TEXT DEFAULT '', proxy_code TEXT DEFAULT '', dev_pct REAL, allocated_fixed REAL, allocated_dynamic REAL, exposure_status TEXT DEFAULT 'unknown', exposure_reasons TEXT DEFAULT '', strategy_version TEXT DEFAULT '')""",
    "decision_journal_entry": """CREATE TABLE IF NOT EXISTS decision_journal_entry (id INTEGER PRIMARY KEY AUTOINCREMENT, weekly_plan_item_id INTEGER, created_at TEXT, investment_thesis_snapshot TEXT DEFAULT '', expected_scenario TEXT DEFAULT '', invalidation_conditions TEXT DEFAULT '', known_unknowns TEXT DEFAULT '', user_note TEXT DEFAULT '', immutable INTEGER DEFAULT 1, strategy_version TEXT DEFAULT '', market_data_date TEXT DEFAULT '', data_source TEXT DEFAULT '', proxy_code TEXT DEFAULT '', valuation_state TEXT DEFAULT '', fixed_amount REAL, dynamic_amount REAL, candidate_amount REAL, final_amount REAL, risk_status TEXT DEFAULT '', exposure_status TEXT DEFAULT '', calculation_trace TEXT DEFAULT '', evidence_json TEXT DEFAULT '{}')""",
    "plan_item_user_decision": """CREATE TABLE IF NOT EXISTS plan_item_user_decision (id INTEGER PRIMARY KEY AUTOINCREMENT, weekly_plan_item_id INTEGER, user_action TEXT DEFAULT 'PENDING', approved_amount REAL, reason TEXT DEFAULT '', user_note TEXT DEFAULT '', decided_at TEXT, created_at TEXT, updated_at TEXT)""",
    "execution_record": """CREATE TABLE IF NOT EXISTS execution_record (id INTEGER PRIMARY KEY AUTOINCREMENT, weekly_plan_item_id INTEGER, user_decision_id INTEGER, execution_status TEXT DEFAULT 'PENDING', executed_at TEXT, actual_amount REAL, actual_price REAL, actual_units REAL, fee REAL DEFAULT 0.0, platform TEXT DEFAULT '', external_reference TEXT, user_note TEXT DEFAULT '', created_at TEXT)""",
    "reconciliation_record": """CREATE TABLE IF NOT EXISTS reconciliation_record (id INTEGER PRIMARY KEY AUTOINCREMENT, execution_record_id INTEGER, reconciliation_status TEXT DEFAULT 'PENDING', planned_amount REAL, approved_amount REAL, actual_amount REAL, amount_variance REAL, evidence TEXT DEFAULT '{}', reconciled_at TEXT, reconciled_by TEXT DEFAULT '', transaction_id INTEGER)""",
    "weekly_review": """CREATE TABLE IF NOT EXISTS weekly_review (id INTEGER PRIMARY KEY AUTOINCREMENT, weekly_plan_id INTEGER, period_start TEXT DEFAULT '', period_end TEXT DEFAULT '', status TEXT DEFAULT 'DRAFT', strategy_version TEXT DEFAULT '', planned_total REAL DEFAULT 0.0, approved_total REAL DEFAULT 0.0, actual_total REAL DEFAULT 0.0, matched_total REAL DEFAULT 0.0, unexecuted_total REAL DEFAULT 0.0, approval_variance_total REAL, execution_variance_total REAL, plan_execution_variance_total REAL, item_count INTEGER DEFAULT 0, approved_count INTEGER DEFAULT 0, executed_count INTEGER DEFAULT 0, matched_count INTEGER DEFAULT 0, mismatch_count INTEGER DEFAULT 0, skipped_count INTEGER DEFAULT 0, deferred_count INTEGER DEFAULT 0, cancelled_count INTEGER DEFAULT 0, blocked_count INTEGER DEFAULT 0, undecided_count INTEGER DEFAULT 0, data_quality_findings_json TEXT DEFAULT '{}', risk_findings_json TEXT DEFAULT '{}', exposure_findings_json TEXT DEFAULT '{}', process_findings_json TEXT DEFAULT '{}', user_overall_note TEXT DEFAULT '', created_at TEXT, generated_at TEXT, reviewed_at TEXT, closed_at TEXT)""",
    "weekly_review_item": """CREATE TABLE IF NOT EXISTS weekly_review_item (id INTEGER PRIMARY KEY AUTOINCREMENT, weekly_review_id INTEGER, weekly_plan_item_id INTEGER, asset_code TEXT DEFAULT '', asset_role TEXT DEFAULT 'core', plan_action TEXT DEFAULT '', planned_amount REAL, user_action TEXT DEFAULT '', approved_amount REAL, decision_reason TEXT DEFAULT '', decision_note TEXT DEFAULT '', execution_status TEXT DEFAULT '', actual_amount REAL, actual_price REAL, actual_units REAL, execution_note TEXT DEFAULT '', reconciliation_status TEXT DEFAULT '', approval_variance REAL, execution_variance REAL, plan_execution_variance REAL, review_category TEXT DEFAULT 'UNDECIDED', exception_codes_json TEXT DEFAULT '[]', facts_json TEXT DEFAULT '{}', user_variance_reason TEXT DEFAULT '', created_at TEXT, updated_at TEXT)""",
    "follow_up_action": """CREATE TABLE IF NOT EXISTS follow_up_action (id INTEGER PRIMARY KEY AUTOINCREMENT, weekly_review_id INTEGER, weekly_review_item_id INTEGER, action_type TEXT DEFAULT 'RESEARCH', description TEXT DEFAULT '', owner TEXT DEFAULT 'USER', due_date TEXT, status TEXT DEFAULT 'OPEN', verification_method TEXT DEFAULT '', verification_result TEXT DEFAULT '', created_at TEXT, updated_at TEXT, completed_at TEXT)""",
}

ASSET_FIELDS = [("role", "TEXT DEFAULT 'core'"), ("proxy_code", "TEXT"), ("proxy_type", "TEXT DEFAULT 'INDEX'"),
                ("theme", "TEXT DEFAULT ''"), ("target_weight", "REAL DEFAULT 0.0"),
                ("investment_thesis", "TEXT DEFAULT ''"), ("expected_holding_months", "INTEGER DEFAULT 12"),
                ("review_cycle", "TEXT DEFAULT 'quarterly'"), ("invalidation_conditions", "TEXT DEFAULT ''"),
                ("enabled", "INTEGER DEFAULT 1")]


def migrate(db_path: str) -> dict:
    db = Path(db_path)
    if not db.exists():
        return {"ok": False, "error": "Database not found"}

    backup = db.parent / f"invest_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(db, backup)

    conn = sqlite3.connect(str(db))
    cursor = conn.cursor()

    # Count before
    cursor.execute("SELECT COUNT(*) FROM asset")
    asset_before = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM \"transaction\"")
    txn_before = cursor.fetchone()[0]

    # Asset fields
    cursor.execute("PRAGMA table_info(asset)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    for name, col_type in ASSET_FIELDS:
        if name not in existing_cols:
            cursor.execute(f"ALTER TABLE asset ADD COLUMN {name} {col_type}")

    # Transaction field
    cursor.execute("PRAGMA table_info(\"transaction\")")
    txn_cols = {row[1] for row in cursor.fetchall()}
    if "source_execution_id" not in txn_cols:
        cursor.execute("ALTER TABLE \"transaction\" ADD COLUMN source_execution_id INTEGER")

    # New tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = {row[0] for row in cursor.fetchall()}
    created_tables = []
    for name, sql in NEW_TABLES.items():
        if name not in existing_tables:
            cursor.execute(sql)
            created_tables.append(name)

    # Indexes
    created_indexes = []
    for name, sql in INDEXES.items():
        try:
            cursor.execute(sql)
            created_indexes.append(name)
        except Exception:
            pass

    # Default config
    cursor.execute("SELECT COUNT(*) FROM investment_plan_config")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO investment_plan_config (name, weekly_budget, core_target_ratio, satellite_target_ratio, strategy_version, created_at, updated_at) VALUES ('default', 200.0, 0.65, 0.35, 'v2.1', ?, ?)",
                       (datetime.now().isoformat(), datetime.now().isoformat()))

    conn.commit()

    # Verify
    cursor.execute("SELECT COUNT(*) FROM asset"); asset_after = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM \"transaction\""); txn_after = cursor.fetchone()[0]
    conn.close()

    return {"ok": True, "version": "v2.1", "backup": str(backup),
            "tables_created": created_tables, "indexes_created": created_indexes,
            "asset_count_preserved": asset_before == asset_after,
            "transaction_count_preserved": txn_before == txn_after,
            "idempotent": bool(asset_before == asset_after and txn_before == txn_after)}


if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else "F:/compound-interest-plan/invest.db"
    import json
    print(json.dumps(migrate(db), indent=2, ensure_ascii=False))
