#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一 API 服务层 — 数据库唯一写入口

架构原则：
    - 数据库是唯一事实源
    - api_service 是唯一写入口
    - 所有写入经过 risk_guard / accounting 校验
    - 幂等键防重复写入
    - created_by 追踪来源

禁止：
    - GUI 直接写 SQLite ✗
    - Hermes 直接写 SQLite ✗
    - daily job 绕过 risk_guard ✗
"""

import sqlite3
import json
import logging
from datetime import date as Date, datetime
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

from ..core.models import (
    make_sample_idempotency_key,
    make_tx_idempotency_key,
    make_pool_idempotency_key,
)
from ..core.strategy import calculate_dca_allocation as calc_dca, calculate_ma200_deviation
from ..core.risk_guard import advice_allowed, RiskResult
from ..services.accounting import calculate_holdings as calc_holdings
from ..db.storage import connect_db, query_df

logger = logging.getLogger(__name__)

DB_PATH = Path("data/trend.db")

# ── 幂等检查 ────────────────────────────────────────

def _check_idempotency(
    con: sqlite3.Connection, table: str, idempotency_key: str
) -> Optional[dict]:
    """检查幂等键是否已存在。存在返回已有记录，不存在返回 None。"""
    if not idempotency_key:
        return None

    try:
        con.row_factory = sqlite3.Row
        row = con.execute(
            f"SELECT * FROM {table} WHERE idempotency_key=? LIMIT 1",
            (idempotency_key,),
        ).fetchone()
        con.row_factory = None
        if row:
            return dict(row)
    except sqlite3.OperationalError:
        pass
    return None


def _ensure_idempotency_col(con: sqlite3.Connection, table: str):
    """确保 idempotency_key 列存在"""
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    if "idempotency_key" not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN idempotency_key TEXT")
    if "created_by" not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN created_by TEXT DEFAULT 'unknown'")


# ── 数据采样 ─────────────────────────────────────────

def api_daily_sample(
    fund_cfg: dict,
    created_by: str = "scheduler",
    force: bool = False,
) -> Dict[str, Any]:
    """
    POST /api/snapshot/daily/run

    对单个基金执行完整的采样 → 偏离计算 → risk_guard → 持久化。
    幂等：同一天同基金重复调用返回已有结果。
    """
    from ..core.data_sources import (
        get_latest_nav_with_fallback,
        get_index_data_with_fallback,
    )

    fund_code = fund_cfg["fund_code"]
    today = Date.today().isoformat()
    now_ts = int(datetime.now().timestamp())
    idem_key = make_sample_idempotency_key(fund_code, today)

    # 幂等检查
    if not force:
        with connect_db() as con:
            _ensure_idempotency_col(con, "dca_plan_v2")
            existing = con.execute(
                "SELECT * FROM dca_plan_v2 WHERE fund_code=? AND date=? AND idempotency_key=? LIMIT 1",
                (fund_code, today, idem_key),
            ).fetchone()
            if existing:
                logger.info(f"[{fund_code}] 幂等命中: {idem_key}")
                return {
                    "fund_code": fund_code,
                    "status": "idempotent",
                    "idempotency_key": idem_key,
                    "existing_plan_date": existing[1],
                }

    # 1) NAV & 代理指数
    nav, nav_src, _ = get_latest_nav_with_fallback(
        fund_code, fund_cfg.get("fund_name_en", "")
    )
    df_idx, idx_src, _ = get_index_data_with_fallback(
        fund_cfg.get("proxy_index", ""), fund_cfg.get("proxy_index_en", "")
    )

    if df_idx.empty or "close" not in df_idx.columns:
        return {"fund_code": fund_code, "error": "代理指数数据为空", "risk_guard_passed": False}

    if "ma200" not in df_idx.columns:
        df_idx["ma200"] = df_idx["close"].rolling(200).mean()

    last = df_idx.iloc[-1]
    proxy_close = float(last["close"])
    proxy_ma200 = float(last["ma200"])

    # 2) MA200 偏离度
    try:
        dev_pct = calculate_ma200_deviation(proxy_close, proxy_ma200)
    except ValueError as e:
        return {"fund_code": fund_code, "error": f"MA200计算失败: {e}", "risk_guard_passed": False}

    from ..core.strategy import classify_dev_pct
    level = classify_dev_pct(dev_pct)

    # 3) 准备金
    with connect_db() as con:
        row = con.execute(
            "SELECT reserve_balance, last_signal_date, last_low_trigger_date FROM fund_state WHERE fund_code=?",
            (fund_code,),
        ).fetchone()
        reserve_balance = float(row[0]) if row else 0.0

    # 4) 定投建议
    plan_result = calc_dca(fund_cfg, reserve_balance, dev_pct)

    # 5) 持仓
    hcfg = fund_cfg.get("manual_holdings", {})
    hold = {}
    if hcfg.get("enabled") and nav is not None:
        try:
            holding = calc_holdings(
                units=hcfg["units_left"], avg_cost=hcfg["avg_cost"],
                current_nav=nav, realized_pnl=hcfg.get("realized_pnl", 0.0),
            )
            hold = {
                "units": float(holding.units), "market_value": float(holding.market_value),
                "unrealized_pnl": float(holding.unrealized_pnl),
                "unrealized_pct": float(holding.unrealized_pct),
                "total_pnl": float(holding.total_pnl),
            }
        except ValueError:
            hold = {"units": 0, "market_value": 0, "unrealized_pnl": 0, "unrealized_pct": 0, "total_pnl": 0}

    # 6) risk_guard
    risk = advice_allowed(
        nav=nav, proxy_close=proxy_close, ma200=proxy_ma200,
        dev_pct=dev_pct, source=idx_src, plan=plan_result,
        weekly_budget=fund_cfg.get("weekly_budget", 200.0),
    )

    calculation_trace = {
        "fund_nav": nav,
        "fund_nav_date": str(last.get("date", today)),
        "proxy_code": fund_cfg.get("proxy_index", ""),
        "proxy_close": proxy_close,
        "proxy_ma200": proxy_ma200,
        "dev_pct": dev_pct,
        "data_source": idx_src,
        "is_trusted": idx_src.lower() != "mock",
        "risk_guard_passed": risk.passed,
        "risk_guard_errors": risk.errors,
        "fixed_amount": plan_result.fixed_amount,
        "dynamic_amount": plan_result.dynamic_amount,
        "reserve_before": plan_result.reserve_before,
        "reserve_after": plan_result.reserve_after,
    }

    # 7) 持久化
    with connect_db() as con:
        _ensure_idempotency_col(con, "nav_daily_v2")
        _ensure_idempotency_col(con, "proxy_daily_v2")
        _ensure_idempotency_col(con, "dca_plan_v2")
        _ensure_idempotency_col(con, "holdings_snapshot_v2")

        con.execute(
            "INSERT OR REPLACE INTO nav_daily_v2 VALUES (?,?,?,?,?,?,?)",
            (fund_code, today, float(nav) if nav else 0, nav_src, now_ts, created_by, idem_key),
        )
        con.execute(
            """INSERT OR REPLACE INTO proxy_daily_v2
               (fund_code,date,close,ma200,dev_pct,source,timestamp,created_by,idempotency_key)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (fund_code, today, proxy_close, proxy_ma200, dev_pct, idx_src, now_ts, created_by, idem_key),
        )
        con.execute(
            """INSERT OR REPLACE INTO dca_plan_v2
               (fund_code,date,level,dev_pct,base_amt,dyn_amt,total_amt,reserve_before,reserve_after,timestamp,created_by,idempotency_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fund_code, today, level, dev_pct,
             plan_result.fixed_amount, plan_result.dynamic_amount, plan_result.total_amount,
             plan_result.reserve_before, plan_result.reserve_after, now_ts, created_by, idem_key),
        )
        con.execute(
            """INSERT OR REPLACE INTO holdings_snapshot_v2
               (fund_code,date,units,avg_cost,nav,mtm,unreal_pnl,unreal_pct,total_pnl,timestamp,created_by,idempotency_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fund_code, today,
             hold.get("units", 0), hcfg.get("avg_cost", 0), nav or 0,
             hold.get("market_value", 0), hold.get("unrealized_pnl", 0),
             hold.get("unrealized_pct", 0), hold.get("total_pnl", 0),
             now_ts, created_by, idem_key),
        )
        con.execute(
            """INSERT INTO fund_state(fund_code,reserve_balance,last_signal_date,last_low_trigger_date,updated_at)
               VALUES (?,?,?,?,?) ON CONFLICT(fund_code) DO UPDATE SET
               reserve_balance=excluded.reserve_balance, last_signal_date=excluded.last_signal_date,
               last_low_trigger_date=excluded.last_low_trigger_date, updated_at=excluded.updated_at""",
            (fund_code, plan_result.reserve_after, today,
             today if level == "low" else (row[2] if row else None), now_ts),
        )

    action_allowed = risk.passed and (idx_src.lower() != "mock")

    return {
        "fund_code": fund_code,
        "status": "created",
        "action_allowed": action_allowed,
        "recommended_amount": plan_result.total_amount if action_allowed else None,
        **calculation_trace,
        "calculation_trace": {
            "computed_amount": plan_result.total_amount,
            "fixed_amount": plan_result.fixed_amount,
            "dynamic_amount": plan_result.dynamic_amount,
            "reserve_before": plan_result.reserve_before,
            "reserve_after": plan_result.reserve_after,
        },
        "idempotency_key": idem_key,
        "created_by": created_by,
        "hold": hold,
    }


# ── 查询 ─────────────────────────────────────────────

def api_get_latest(fund_code: str) -> Dict[str, Any]:
    """GET /api/snapshot/latest"""
    result = {"fund_code": fund_code}

    nav = query_df(
        "SELECT * FROM nav_daily_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1", (fund_code,)
    )
    proxy = query_df(
        "SELECT * FROM proxy_daily_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1", (fund_code,)
    )
    plan = query_df(
        "SELECT * FROM dca_plan_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1", (fund_code,)
    )

    if len(nav):
        result["nav"] = float(nav["nav"].iloc[0])
        result["nav_date"] = str(nav["date"].iloc[0])
        result["nav_source"] = str(nav["source"].iloc[0])
    if len(proxy):
        result["proxy_close"] = float(proxy["close"].iloc[0])
        result["proxy_ma200"] = float(proxy["ma200"].iloc[0])
        result["dev_pct"] = float(proxy["dev_pct"].iloc[0])
        result["proxy_date"] = str(proxy["date"].iloc[0])
        result["proxy_source"] = str(proxy["source"].iloc[0])
    if len(plan):
        result["level"] = str(plan["level"].iloc[0])
        result["fixed_amount"] = float(plan["base_amt"].iloc[0])
        result["dynamic_amount"] = float(plan["dyn_amt"].iloc[0])
        result["total_amount"] = float(plan["total_amt"].iloc[0])
        result["reserve_before"] = float(plan["reserve_before"].iloc[0])
        result["reserve_after"] = float(plan["reserve_after"].iloc[0])

    return result


def api_get_plan(fund_code: str) -> Dict[str, Any]:
    """GET /api/plan/latest"""
    result = {"fund_code": fund_code}
    plan = query_df(
        "SELECT * FROM dca_plan_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1", (fund_code,)
    )
    if len(plan):
        from ..core.strategy import classify_dev_pct
        dev_pct_val = float(plan["dev_pct"].iloc[0])
        # NEVER trust stored level — always recompute from dev_pct
        level = classify_dev_pct(dev_pct_val)
        is_trusted = (result.get("proxy_source", "") or "").lower() != "mock"
        action_allowed = is_trusted and level != "invalid"
        computed = float(plan["total_amt"].iloc[0])
        result.update({
            "date": str(plan["date"].iloc[0]),
            "level": level,
            "dev_pct": dev_pct_val,
            "action_allowed": action_allowed,
            "recommended_amount": computed if action_allowed else None,
            "calculation_trace": {
                "fixed_amount": float(plan["base_amt"].iloc[0]),
                "dynamic_amount": float(plan["dyn_amt"].iloc[0]),
                "computed_amount": computed,
                "reserve_before": float(plan["reserve_before"].iloc[0]),
                "reserve_after": float(plan["reserve_after"].iloc[0]),
            },
            "created_by": str(plan["created_by"].iloc[0]) if "created_by" in plan.columns else "unknown",
        })
    else:
        result["action_allowed"] = False
        result["recommended_amount"] = None
        result["calculation_trace"] = {}
    return result


# ── 交易 ─────────────────────────────────────────────

def api_create_transaction(
    fund_code: str, date_str: str, tx_type: str, amount: float,
    units: float = 0.0, nav: float = 0.0, from_pool: bool = False,
    note: str = "", created_by: str = "gui", external_ref: str = "",
    confirmed: bool = False,
) -> Dict[str, Any]:
    """POST /api/transactions"""
    if created_by == "hermes" and not confirmed:
        return {
            "status": "confirmation_required",
            "message": "Hermes 写入交易前必须确认。请设置 confirmed=True。",
            "summary": {
                "fund_code": fund_code, "date": date_str, "type": tx_type,
                "amount": amount, "from_pool": from_pool, "note": note,
            }
        }

    idem_key = make_tx_idempotency_key(fund_code, date_str, tx_type, amount, external_ref)

    # from_pool 余额检查
    if from_pool:
        state = query_df("SELECT reserve_balance FROM fund_state WHERE fund_code=?", (fund_code,))
        balance = float(state["reserve_balance"].iloc[0]) if len(state) else 0.0
        if balance < amount:
            return {"status": "rejected", "error": f"资金池余额不足: 需要 ¥{amount:.2f}，余额 ¥{balance:.2f}"}

    with connect_db() as con:
        # 确保表存在
        try:
            _ensure_idempotency_col(con, "transactions_v2")
        except sqlite3.OperationalError:
            init_transactions_table()
        _ensure_idempotency_col(con, "transactions_v2")
        existing = _check_idempotency(con, "transactions_v2", idem_key)
        if existing:
            return {"status": "idempotent", "idempotency_key": idem_key, "existing": existing}

        con.execute(
            """INSERT INTO transactions_v2 (fund_code, date, tx_type, amount, units, nav, from_pool, note, created_by, idempotency_key)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (fund_code, date_str, tx_type, amount, units, nav, int(from_pool), note, created_by, idem_key),
        )
        tx_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        # from_pool: 更新资金池
        if from_pool:
            con.execute(
                "UPDATE fund_state SET reserve_balance = reserve_balance - ? WHERE fund_code=?",
                (amount, fund_code),
            )
            con.execute(
                """INSERT INTO pool_ledger (fund_code, date, entry_type, amount, balance_after, related_tx_id, note, created_by, idempotency_key)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (fund_code, date_str, "BUY", amount, 0.0, tx_id, note, created_by, idem_key + ":buy"),
            )

    return {
        "status": "created",
        "transaction_id": tx_id,
        "idempotency_key": idem_key,
        "created_by": created_by,
    }


def api_delete_transaction(tx_id: int) -> Dict[str, Any]:
    """DELETE /api/transactions/{id}"""
    with connect_db() as con:
        # 确保表存在
        try:
            _ensure_idempotency_col(con, "transactions_v2")
        except sqlite3.OperationalError:
            init_transactions_table()
        row = con.execute(
            "SELECT * FROM transactions_v2 WHERE id=?", (tx_id,)
        ).fetchone()
        if not row:
            return {"status": "not_found", "error": f"交易 {tx_id} 不存在"}

        fund_code = row[1]
        amount = row[4]
        from_pool = bool(row[7])

        con.execute("DELETE FROM transactions_v2 WHERE id=?", (tx_id,))

        # from_pool 退款
        if from_pool:
            con.execute(
                "UPDATE fund_state SET reserve_balance = reserve_balance + ? WHERE fund_code=?",
                (amount, fund_code),
            )
            con.execute(
                """INSERT INTO pool_ledger (fund_code, date, entry_type, amount, balance_after, related_tx_id, note, created_by)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (fund_code, Date.today().isoformat(), "REFUND", amount, 0.0, tx_id,
                 f"删除交易 #{tx_id} 退款", "api"),
            )

    return {"status": "deleted", "transaction_id": tx_id, "amount_refunded": amount if from_pool else 0}


# ── 资金池 ───────────────────────────────────────────

def api_pool_deposit(
    fund_code: str, amount: float, date_str: str = "",
    note: str = "", created_by: str = "gui",
) -> Dict[str, Any]:
    """POST /api/pool/deposit"""
    if not date_str:
        date_str = Date.today().isoformat()
    idem_key = make_pool_idempotency_key(fund_code, date_str, "DEPOSIT", amount)

    with connect_db() as con:
        _ensure_idempotency_col(con, "pool_ledger")
        existing = _check_idempotency(con, "pool_ledger", idem_key)
        if existing:
            return {"status": "idempotent", "idempotency_key": idem_key, "existing": existing}

        con.execute(
            "UPDATE fund_state SET reserve_balance = reserve_balance + ? WHERE fund_code=?",
            (amount, fund_code),
        )
        con.execute(
            """INSERT INTO pool_ledger (fund_code, date, entry_type, amount, balance_after, note, created_by, idempotency_key)
               VALUES (?,?,?,?,?,?,?,?)""",
            (fund_code, date_str, "DEPOSIT", amount, 0.0, note, created_by, idem_key),
        )

    balance = query_df("SELECT reserve_balance FROM fund_state WHERE fund_code=?", (fund_code,))
    return {
        "status": "deposited",
        "fund_code": fund_code,
        "amount": amount,
        "balance_after": float(balance["reserve_balance"].iloc[0]) if len(balance) else 0,
        "idempotency_key": idem_key,
        "created_by": created_by,
    }


def api_pool_adjust(
    fund_code: str, amount: float, note: str, created_by: str = "manual",
) -> Dict[str, Any]:
    """POST /api/pool/adjust"""
    date_str = Date.today().isoformat()
    idem_key = make_pool_idempotency_key(fund_code, date_str, "ADJUST", amount)

    with connect_db() as con:
        _ensure_idempotency_col(con, "pool_ledger")
        existing = _check_idempotency(con, "pool_ledger", idem_key)
        if existing:
            return {"status": "idempotent", "idempotency_key": idem_key, "existing": existing}

        con.execute(
            "UPDATE fund_state SET reserve_balance = reserve_balance + ? WHERE fund_code=?",
            (amount, fund_code),
        )
        con.execute(
            """INSERT INTO pool_ledger (fund_code, date, entry_type, amount, balance_after, note, created_by, idempotency_key)
               VALUES (?,?,?,?,?,?,?,?)""",
            (fund_code, date_str, "ADJUST", amount, 0.0, note, created_by, idem_key),
        )

    return {"status": "adjusted", "fund_code": fund_code, "amount": amount, "note": note,
            "idempotency_key": idem_key, "created_by": created_by}


def api_pool_ledger(fund_code: str, limit: int = 50) -> List[Dict[str, Any]]:
    """GET /api/pool/ledger"""
    rows = query_df(
        "SELECT * FROM pool_ledger WHERE fund_code=? ORDER BY date DESC, id DESC LIMIT ?",
        (fund_code, limit),
    )
    if len(rows) == 0:
        return []
    return rows.to_dict("records")


# ── 周复盘 ───────────────────────────────────────────

def api_weekly_report(fund_code: Optional[str] = None, days: int = 7) -> Dict[str, Any]:
    """GET /api/reports/weekly"""
    from ..services.actions import generate_weekly_narrative
    narrative = generate_weekly_narrative(fund_code, days)

    start = (Date.today() - __import__('datetime').timedelta(days=days - 1)).isoformat()
    params = (start,) if fund_code is None else (fund_code, start)
    where = "WHERE date>=?" if fund_code is None else "WHERE fund_code=? AND date>=?"
    df = query_df(
        f"SELECT * FROM dca_plan_v2 {where} ORDER BY fund_code, date", params
    )

    return {
        "period_days": days,
        "fund_code": fund_code or "all",
        "narrative": narrative,
        "total_amount": float(df["total_amt"].sum()) if len(df) else 0,
        "record_count": len(df),
    }


# ── 初始化 transactions_v2 表 ─────────────────────────

def init_transactions_table():
    """创建 transactions_v2 表（安全，不删数据）"""
    with connect_db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS transactions_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code TEXT NOT NULL,
                date TEXT NOT NULL,
                tx_type TEXT NOT NULL DEFAULT 'BUY',
                amount REAL NOT NULL DEFAULT 0,
                units REAL DEFAULT 0,
                nav REAL DEFAULT 0,
                from_pool INTEGER DEFAULT 0,
                note TEXT DEFAULT '',
                created_by TEXT DEFAULT 'unknown',
                idempotency_key TEXT UNIQUE,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_tx_v2_fund ON transactions_v2(fund_code)"
        )
        # 确保旧表也有列
        for table in ["nav_daily_v2", "proxy_daily_v2", "dca_plan_v2",
                       "holdings_snapshot_v2", "pool_ledger"]:
            _ensure_idempotency_col(con, table)
    logger.info("✓ transactions_v2 表初始化完成")
