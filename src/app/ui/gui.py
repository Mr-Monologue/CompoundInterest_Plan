#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定投助手 — GUI 入口（v2.0 统一 API 版）

所有数据读写走 api_service 层。
GUI 不直接写 SQLite，不重复实现策略公式。
"""

import streamlit as st
import pandas as pd
import sys
from pathlib import Path
from datetime import date as DateType

project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from src.app.core.config import load_all_funds_config, save_config
from src.app.db.storage import init_db
from src.app.core.risk_guard import advice_allowed, format_rejection_message
from src.app.services.api_service import (
    api_get_latest, api_get_plan, api_daily_sample,
    api_create_transaction, api_delete_transaction,
    api_pool_deposit, api_pool_ledger, api_weekly_report,
    init_transactions_table,
)
from src.app.services.actions import add_fund_to_config

st.set_page_config(page_title="定投助手", layout="wide")
init_db()
init_transactions_table()

# 侧边栏
funds, raw_cfg = load_all_funds_config()
code_to_cfg = {f["fund_code"]: f for f in funds}

st.sidebar.header("基金管理")
selected = st.sidebar.selectbox(
    "选择基金", ["(全部)"] + [f["fund_code"] for f in funds]
)

with st.sidebar.expander("➕ 添加基金", expanded=False):
    with st.form("add_fund"):
        fc = st.text_input("基金代码", placeholder="000083")
        fn = st.text_input("基金名称", placeholder="汇添富消费行业混合")
        fe = st.text_input("yfinance代码", placeholder="000083.SZ")
        pi = st.text_input("代理指数", placeholder="000932")
        pie = st.text_input("代理指数_en", placeholder="000932.SS")
        wb = st.number_input("每周预算", min_value=0.0, value=200.0, step=50.0)
        if st.form_submit_button("保存到配置"):
            add_fund_to_config({
                "fund_code": fc, "fund_name": fn, "fund_name_en": fe,
                "proxy_index": pi, "proxy_index_en": pie, "weekly_budget": wb,
                "manual_holdings": {"enabled": True, "units_left": 0.0, "avg_cost": 0.0, "realized_pnl": 0.0},
            })
            st.success("已添加")
            st.rerun()

if selected != "(全部)":
    if st.sidebar.button("📥 采样并保存（估值+建议）"):
        with st.spinner("正在采集数据..."):
            r = api_daily_sample(code_to_cfg[selected], created_by="gui")
        if r.get("risk_guard_passed"):
            st.success(f"{selected} 采样完成 — risk_guard ✅")
        else:
            st.warning(f"{selected} 采样完成 — risk_guard ❌（详见基金详情）")
        st.rerun()

tabs = st.tabs(["📊 总览", "🔍 基金详情", "📈 持仓 & 交易", "💵 资金池", "📅 周复盘"])

# ── 总览 ──────────────────────────────────────────
with tabs[0]:
    st.header("📊 投资组合总览")
    rows = []
    for f in funds:
        code = f["fund_code"]
        data = api_get_latest(code)
        plan = api_get_plan(code)
        if not data.get("nav"):
            continue
        action_ok = plan.get("action_allowed", False)
        rec = plan.get("recommended_amount")
        trace = plan.get("calculation_trace", {})
        rows.append({
            "基金": f"{code} {f['fund_name']}",
            "净值": data.get("nav"),
            "偏离%": round(data.get("dev_pct", 0) * 100, 2),
            "估值": plan.get("level", "?").upper(),
            "状态": "✅ OK" if action_ok else "⛔ BLOCKED",
            "建议(¥)": f"¥{rec:.2f}" if rec is not None else "null",
            "准备金": trace.get("reserve_after"),
            "日期": data.get("nav_date", "?"),
            "来源": plan.get("created_by", "?"),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    else:
        st.info("暂无数据。请在侧边栏选择基金并点击采样。")

# ── 基金详情 ────────────────────────────────────────
with tabs[1]:
    st.header("🔍 基金详情")
    if selected == "(全部)":
        st.info("请选择左侧具体基金")
    else:
        code = selected
        data = api_get_latest(code)
        plan = api_get_plan(code)

        if not data.get("nav"):
            st.warning("尚无净值数据")
            st.stop()

        st.subheader("📋 数据来源 & 估值指标")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("基金净值", f"{data.get('nav',0):.4f}")
        c2.metric("净值日期", str(data.get("nav_date", "?")))
        c3.metric("净值源", str(data.get("nav_source", "?")))
        c4.metric("代理指数源", str(data.get("proxy_source", "?")))

        c1, c2, c3, c4 = st.columns(4)
        proxy_close = data.get("proxy_close")
        proxy_ma200 = data.get("proxy_ma200")
        dev_pct = data.get("dev_pct", 0)
        c1.metric("代理指数", f"{proxy_close:.0f}" if proxy_close else "N/A")
        c2.metric("MA200", f"{proxy_ma200:.1f}" if proxy_ma200 else "N/A")
        c3.metric("MA200 偏离", f"{dev_pct*100:.2f}%")
        c4.metric("估值层级", {"low": "🔴 低估", "mid": "🟡 合理", "high": "🟢 偏高"}.get(plan.get("level"), "?"))

        # risk_guard — 使用 API 返回的 action_allowed
        st.subheader("🛡️ 风险防护")
        action_ok = plan.get("action_allowed", False)
        rec = plan.get("recommended_amount")
        trace = plan.get("calculation_trace", {})

        if not action_ok:
            st.error("⛔ BLOCKED — 数据异常，需要人工复核")
            # 从 risk_guard 获取失败原因
            risk = advice_allowed(
                nav=data.get("nav"), proxy_close=proxy_close, ma200=proxy_ma200,
                dev_pct=dev_pct, source=data.get("proxy_source", ""),
            )
            for e in risk.errors:
                st.warning(f"• {e}")
            st.caption(f"recommended_amount = null（computed_amount={trace.get('computed_amount',0):.2f} 仅供审计）")
        else:
            st.success("✅ 风险防护通过 — 数据可信")
            st.subheader("💰 本周定投建议")
            c1, c2, c3 = st.columns(3)
            c1.metric("固定定投", f"¥{trace.get('fixed_amount',0):.2f}")
            c2.metric("动态定投", f"¥{trace.get('dynamic_amount',0):.2f}")
            c3.metric("建议金额", f"¥{rec:.2f}" if rec is not None else "null",
                      delta=f"准备金: ¥{trace.get('reserve_before',0):.0f} → ¥{trace.get('reserve_after',0):.0f}")

            # 审计信息
            with st.expander("📋 审计详情 (calculation_trace)"):
                st.json({
                    "fund_code": code, "fund_nav": data.get("nav"),
                    "fund_nav_date": str(data.get("nav_date", "")),
                    "proxy_code": code_to_cfg[code].get("proxy_index", ""),
                    "proxy_close": proxy_close, "proxy_ma200": proxy_ma200,
                    "dev_pct": dev_pct, "level": plan.get("level"),
                    "data_source": data.get("proxy_source", ""),
                    "action_allowed": action_ok,
                    "recommended_amount": rec,
                    "calculation_trace": trace,
                    "created_by": plan.get("created_by", "unknown"),
                })

# ── 持仓 & 交易 ──────────────────────────────────────
with tabs[2]:
    st.header("📈 持仓 & 交易管理")
    if selected == "(全部)":
        st.info("请选择左侧具体基金")
    else:
        code = selected
        f = code_to_cfg[code]

        st.subheader("手动持仓（保存到配置）")
        with st.form("holdings_form"):
            units = st.number_input("剩余份额", value=float(f["manual_holdings"]["units_left"]), step=0.01)
            avg = st.number_input("平均成本", value=float(f["manual_holdings"]["avg_cost"]), step=0.0001, format="%.4f")
            realized = st.number_input("已实现盈亏", value=float(f["manual_holdings"]["realized_pnl"]), step=0.01)
            if st.form_submit_button("保存"):
                f["manual_holdings"]["enabled"] = True
                f["manual_holdings"]["units_left"] = units
                f["manual_holdings"]["avg_cost"] = avg
                f["manual_holdings"]["realized_pnl"] = realized
                _, cfg = load_all_funds_config()
                for i, ff in enumerate(cfg["funds"]):
                    if ff["fund_code"] == code: cfg["funds"][i] = f; break
                save_config(cfg)
                st.success("已保存")

        st.subheader("➕ 新增交易")
        with st.form("tx_form"):
            tx_c1, tx_c2 = st.columns(2)
            tx_date = tx_c1.date_input("日期", DateType.today()).isoformat()
            tx_type = tx_c2.selectbox("类型", ["BUY", "SELL"])
            tx_amount = st.number_input("金额 (¥)", min_value=0.01, value=80.0, step=10.0)
            tx_units = st.number_input("份额", min_value=0.0, step=0.01)
            tx_nav = st.number_input("净值", min_value=0.0, step=0.0001, format="%.4f")
            tx_from_pool = st.checkbox("从资金池出金 (from_pool)")
            tx_note = st.text_input("备注", placeholder="定投买入")
            if st.form_submit_button("提交交易"):
                r = api_create_transaction(
                    fund_code=code, date_str=tx_date, tx_type=tx_type,
                    amount=tx_amount, units=tx_units, nav=tx_nav,
                    from_pool=tx_from_pool, note=tx_note, created_by="gui",
                )
                if r.get("status") == "rejected":
                    st.error(f"❌ {r.get('error')}")
                else:
                    st.success(f"✅ 交易已记录 (id={r.get('transaction_id')})")

        st.subheader("🗑️ 删除交易")
        tx_del_id = st.number_input("交易 ID", min_value=1, step=1)
        if st.button("删除", key="del_tx"):
            r = api_delete_transaction(tx_del_id)
            if r.get("status") == "not_found":
                st.error("交易不存在")
            else:
                st.success(f"已删除。退款: ¥{r.get('amount_refunded',0):.2f}")

# ── 资金池 ──────────────────────────────────────────
with tabs[3]:
    st.header("💵 资金池")
    if selected == "(全部)":
        st.info("请选择左侧具体基金")
    else:
        code = selected
        st.subheader("➕ 入金")
        with st.form("pool_deposit_form"):
            dep_amount = st.number_input("入金金额 (¥)", min_value=0.01, value=120.0, step=10.0)
            dep_note = st.text_input("备注", placeholder="每周准备金流入")
            if st.form_submit_button("入金"):
                r = api_pool_deposit(code, dep_amount, note=dep_note, created_by="gui")
                st.success(f"入金成功。余额: ¥{r.get('balance_after',0):.2f}")

        st.subheader("➕ 人工调整")
        with st.form("pool_adjust_form"):
            adj_amount = st.number_input("调整金额 (±)", value=0.0, step=10.0)
            adj_note = st.text_input("调整原因（必填）")
            if st.form_submit_button("调整"):
                if not adj_note:
                    st.error("调整原因必填")
                else:
                    r = api_pool_adjust(code, adj_amount, adj_note, created_by="gui")
                    st.success("已调整")

        st.subheader("📒 资金池流水")
        ledger = api_pool_ledger(code, limit=20)
        if ledger:
            st.dataframe(pd.DataFrame(ledger), use_container_width=True)
        else:
            st.info("暂无流水记录")

# ── 周复盘 ──────────────────────────────────────────
with tabs[4]:
    st.subheader("每周复盘")
    days = st.slider("统计天数", 7, 30, 7)
    fund_param = None if selected == "(全部)" else selected
    report = api_weekly_report(fund_param, days)
    if report.get("narrative"):
        st.markdown(report["narrative"])
        st.metric("期间总投入", f"¥{report.get('total_amount',0):.2f}")
    else:
        st.info("暂无复盘数据。")

st.markdown("---")
st.caption("v2.0 统一 API 版 — 所有操作经 api_service 层 | created_by 可追溯")
