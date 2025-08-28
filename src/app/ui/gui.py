#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定投助手 - 全功能 GUI 入口
"""

import streamlit as st
import pandas as pd
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from src.app.core.config import load_all_funds_config, save_config
from src.app.db.storage import init_db, query_df
from src.app.services.actions import (
    sample_and_store_one,
    add_fund_to_config,
    generate_weekly_narrative,
)

# 页面配置
st.set_page_config(page_title="定投助手", layout="wide")

# 初始化数据库
init_db()

# 侧边栏：基金选择 & 添加基金 & 采样按钮
funds, raw_cfg = load_all_funds_config()
code_to_cfg = {f["fund_code"]: f for f in funds}

st.sidebar.header("基金管理")
selected = st.sidebar.selectbox(
    "选择基金", ["(全部)"] + [f["fund_code"] for f in funds]
)

with st.sidebar.expander("➕ 添加基金", expanded=False):
    with st.form("add_fund"):
        fund_code = st.text_input("基金代码", placeholder="000083")
        fund_name = st.text_input("基金名称", placeholder="汇添富消费行业混合")
        fund_name_en = st.text_input("yfinance代码", placeholder="000083.SZ")
        proxy_index = st.text_input("代理指数", placeholder="000932")
        proxy_index_en = st.text_input("代理指数_en", placeholder="000932.SS")
        weekly_budget = st.number_input(
            "每周预算", min_value=0.0, value=200.0, step=50.0
        )
        submitted = st.form_submit_button("保存到配置")
        if submitted:
            add_fund_to_config(
                {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "fund_name_en": fund_name_en,
                    "proxy_index": proxy_index,
                    "proxy_index_en": proxy_index_en,
                    "weekly_budget": weekly_budget,
                    "manual_holdings": {
                        "enabled": True,
                        "units_left": 0.0,
                        "avg_cost": 0.0,
                        "realized_pnl": 0.0,
                    },
                }
            )
            st.success("已添加，点击左上角 rerun")
            st.rerun()

if selected != "(全部)":
    if st.sidebar.button("📥 采样并保存（估值+建议）"):
        res = sample_and_store_one(code_to_cfg[selected])
        st.session_state["last_sample"] = res
        st.success(f"{selected} 已采样入库")
        st.rerun()

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["📊 总览", "🔍 基金详情", "📈 持仓", "📅 周复盘"])

# ---- 总览 ----
with tab1:
    st.header("📊 投资组合总览")
    rows = []
    for f in funds:
        code = f["fund_code"]
        plan = query_df(
            "SELECT * FROM dca_plan_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (code,),
        )
        proxy = query_df(
            "SELECT * FROM proxy_daily_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (code,),
        )
        nav = query_df(
            "SELECT * FROM nav_daily_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (code,),
        )
        if len(plan) == 0 or len(proxy) == 0 or len(nav) == 0:
            continue
        rows.append(
            {
                "基金": f"{code} {f['fund_name']}",
                "净值": nav["nav"].iloc[0],
                "偏离%": proxy["dev_pct"].iloc[0],
                "估值": plan["level"].iloc[0].upper(),
                "建议(¥)": plan["total_amt"].iloc[0],
                "固定/动态(¥)": f"{plan['base_amt'].iloc[0]:.2f}/{plan['dyn_amt'].iloc[0]:.2f}",
                "准备金(¥)": plan["reserve_after"].iloc[0],
                "日期": plan["date"].iloc[0],
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    else:
        st.info("暂无数据。先在侧边栏选择基金并点击采样。")

# ---- 基金详情 ----
with tab2:
    st.header("🔍 基金详情")
    if selected == "(全部)":
        st.info("请选择左侧具体基金")
    else:
        code = selected
        col1, col2, col3, col4 = st.columns(4)
        nav = query_df(
            "SELECT * FROM nav_daily_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (code,),
        )
        proxy = query_df(
            "SELECT * FROM proxy_daily_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (code,),
        )
        plan = query_df(
            "SELECT * FROM dca_plan_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (code,),
        )
        if len(nav) == 0:
            st.warning("尚无净值数据")
            st.stop()
        col1.metric("当前净值", f"{nav['nav'].iloc[0]:.4f}")
        if len(proxy):
            col2.metric("MA200 偏离", f"{proxy['dev_pct'].iloc[0]:.2f}%")
        if len(plan):
            col3.metric("本周建议", f"¥{plan['total_amt'].iloc[0]:.2f}")
            col4.metric("准备金余额", f"¥{plan['reserve_after'].iloc[0]:.2f}")

        # 历史图表（净值&MA200、偏离、建议）
        nav_hist = query_df(
            "SELECT date,nav FROM nav_daily_v2 WHERE fund_code=? ORDER BY date", (code,)
        )
        idx_hist = query_df(
            "SELECT date,close,ma200,dev_pct FROM proxy_daily_v2 WHERE fund_code=? ORDER BY date",
            (code,),
        )
        plan_hist = query_df(
            "SELECT date,total_amt,base_amt,dyn_amt FROM dca_plan_v2 WHERE fund_code=? ORDER BY date",
            (code,),
        )

        if len(idx_hist) > 0:
            st.subheader("指数走势 & MA200")
            st.line_chart(idx_hist.set_index("date")[["close", "ma200"]])

            st.subheader("MA200 偏离度")
            st.line_chart(
                idx_hist.set_index("date")[["dev_pct"]].rename(
                    columns={"dev_pct": "MA200偏离%"}
                )
            )

        if len(plan_hist) > 0:
            st.subheader("定投建议历史")
            st.bar_chart(
                plan_hist.set_index("date")[["base_amt", "dyn_amt", "total_amt"]]
            )

# ---- 持仓 ----
with tab3:
    st.header("📈 持仓管理")
    if selected == "(全部)":
        st.info("请选择左侧具体基金")
    else:
        f = code_to_cfg[selected]
        st.subheader("手动持仓（保存到配置）")
        with st.form("holdings_form"):
            units = st.number_input(
                "剩余份额", value=float(f["manual_holdings"]["units_left"]), step=0.01
            )
            avg = st.number_input(
                "平均成本",
                value=float(f["manual_holdings"]["avg_cost"]),
                step=0.0001,
                format="%.4f",
            )
            realized = st.number_input(
                "已实现盈亏",
                value=float(f["manual_holdings"]["realized_pnl"]),
                step=0.01,
            )
            ok = st.form_submit_button("保存")
            if ok:
                f["manual_holdings"]["enabled"] = True
                f["manual_holdings"]["units_left"] = units
                f["manual_holdings"]["avg_cost"] = avg
                f["manual_holdings"]["realized_pnl"] = realized
                # 写回 config.json
                _, cfg = load_all_funds_config()
                for i, ff in enumerate(cfg["funds"]):
                    if ff["fund_code"] == f["fund_code"]:
                        cfg["funds"][i] = f
                        break
                save_config(cfg)
                st.success("已保存，请重新采样更新快照")

        # 展示最新快照
        snap = query_df(
            "SELECT * FROM holdings_snapshot_v2 WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (selected,),
        )
        if len(snap):
            st.subheader("最新持仓快照")
            st.table(snap)

# ---- 周复盘 ----
with tab4:
    st.subheader("每周复盘")
    days = st.slider("统计天数", 7, 30, 7, step=1, help="默认最近 7 天")

    if selected == "(全部)":
        # 显示组合周复盘文字总结
        st.markdown(generate_weekly_narrative(None, days))

        # 保留原有的表格和图表
        st.subheader("详细数据表格")
        df = query_df(
            """SELECT fund_code, date, level, dev_pct, total_amt, reserve_before, reserve_after
                         FROM dca_plan_v2 WHERE date >= date('now','-{} day') ORDER BY fund_code, date""".format(
                days
            )
        )
        if len(df):
            st.dataframe(df, use_container_width=True)
            # 按基金汇总
            agg = df.groupby("fund_code")[["total_amt"]].sum()
            st.subheader("各基金总投入")
            st.bar_chart(agg)
        else:
            st.info(f"最近 {days} 天没有数据。")
    else:
        # 显示单个基金的周复盘文字总结
        st.markdown(generate_weekly_narrative(selected, days))

        # 保留原有的明细表/图
        st.subheader("详细数据表格")
        df = query_df(
            """SELECT date, level, dev_pct, base_amt, dyn_amt, total_amt, reserve_before, reserve_after
                         FROM dca_plan_v2 WHERE fund_code=? AND date >= date('now','-{} day') ORDER BY date""".format(
                days
            ),
            (selected,),
        )
        if len(df):
            st.dataframe(df, use_container_width=True)
            st.subheader("定投详情")
            st.bar_chart(df.set_index("date")[["base_amt", "dyn_amt", "total_amt"]])
        else:
            st.info(f"最近 {days} 天没有数据。")

# 页脚
st.markdown("---")
st.markdown(
    "💡 **使用提示**: 先在侧边栏添加基金，然后选择基金并点击'采样并保存'获取最新数据"
)
