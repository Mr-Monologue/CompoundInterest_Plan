"""v2.1 Migration — real tests."""
import pytest, sqlite3, os, tempfile, json
from pathlib import Path


@pytest.fixture
def old_db():
    """Create an old-version database with pre-v2.1 tables."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(tmp.name)
    conn.execute("CREATE TABLE asset (id INTEGER PRIMARY KEY, code TEXT, name TEXT, type TEXT, max_weight_limit REAL)")
    conn.execute("INSERT INTO asset (code, name, type, max_weight_limit) VALUES ('000083', '消费行业', 'ETF', 0.25)")
    conn.execute('CREATE TABLE "transaction" (id INTEGER PRIMARY KEY, asset_code TEXT, date TEXT, type TEXT, price REAL, amount REAL, fee REAL, units REAL)')
    conn.execute("INSERT INTO \"transaction\" (asset_code, type, price, amount, fee, units) VALUES ('000083','buy',1.5,100,0,66.67)")
    conn.execute("CREATE TABLE dailydecision (id INTEGER PRIMARY KEY, fund_code TEXT, strategy_action TEXT)")
    conn.execute("CREATE TABLE fund_holding_snapshot (id INTEGER PRIMARY KEY, fund_code TEXT)")
    conn.commit(); conn.close()
    return tmp.name


def test_migration_idempotent(old_db):
    import sys
    sys.path.insert(0, "backend")
    from db.migrations import migrate
    # Run 1
    r1 = migrate(old_db)
    assert r1["ok"] is True
    assert r1["asset_count_preserved"] is True
    assert r1["transaction_count_preserved"] is True

    # Run 2 — should be fully idempotent
    r2 = migrate(old_db)
    assert r2["ok"] is True
    assert r2["asset_count_preserved"] is True
    assert r2["transaction_count_preserved"] is True
    assert len(r2.get("migration_errors", [])) == 0

    # Verify schema after both runs
    conn = sqlite3.connect(old_db)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "market_snapshot" in tables
    assert "plan_item_user_decision" in tables
    assert "execution_record" in tables
    assert "reconciliation_record" in tables
    assert "weekly_review" in tables
    assert "weekly_review_item" in tables
    assert "follow_up_action" in tables
    assert "investment_plan_config" in tables
    assert "weekly_investment_plan" in tables

    indexes = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
    assert "uq_item_decision" in indexes
    assert "uq_execution_item" in indexes
    assert "uq_transaction_source_execution" in indexes
    assert "uq_review_plan" in indexes
    assert "uq_review_item" in indexes

    # Asset preserved
    rows = conn.execute("SELECT code, max_weight_limit FROM asset WHERE code='000083'").fetchall()
    assert len(rows) == 1
    assert rows[0][1] == 0.25  # original value preserved

    txns = conn.execute("SELECT COUNT(*) FROM \"transaction\"").fetchone()
    assert txns[0] == 1
    conn.close()
    os.unlink(old_db)


def test_new_asset_fields_present(old_db):
    import sys
    sys.path.insert(0, "backend")
    from db.migrations import migrate
    migrate(old_db)
    conn = sqlite3.connect(old_db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(asset)").fetchall()]
    for f in ["role", "proxy_code", "proxy_type", "theme", "target_weight", "investment_thesis",
              "expected_holding_months", "review_cycle", "invalidation_conditions", "enabled"]:
        assert f in cols, f"Missing asset field: {f}"
    conn.close()
    os.unlink(old_db)
