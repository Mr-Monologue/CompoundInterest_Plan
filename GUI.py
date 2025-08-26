#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
汇添富消费行业混合 定投仪表盘
重构后的4层架构应用
"""

import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
import os

from storage import DB_PATH, init_db
from config import load_all_funds_config, load_config, validate_config
from data_sources import (
    get_latest_nav_with_fallback,
    get_index_data_with_fallback,
    get_data_source_status,
)
from signals import (
    calculate_ma200_deviation,
    calculate_dca_allocation,
    generate_dca_plan_df,
    calculate_ma200_trend,
    get_buy_signals,
)
from holdings import HoldingsCalculator, format_currency, format_percentage
from services.dca_service import run_once_for_fund

# 初始化数据库
init_db()

# 加载配置
funds, raw_cfg = load_all_funds_config()
FUND_MAP = {f["fund_code"]: f for f in funds}

# 侧边栏基金选择
selected_code = st.sidebar.selectbox(
    "选择基金", ["(全部)"] + [f["fund_code"] for f in funds]
)

# 侧边栏刷新按钮
if st.sidebar.button("⚙️ 立即计算选中基金"):
    if selected_code != "(全部)":
        run_once_for_fund(FUND_MAP[selected_code])
        st.success("已计算并入库")
        st.rerun()

# 页面配置
st.set_page_config(
    page_title="汇添富消费行业混合 定投仪表盘",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 初始化会话状态
if "reserve_balance" not in st.session_state:
    st.session_state.reserve_balance = 0.0
if "last_signal_date" not in st.session_state:
    st.session_state.last_signal_date = None
if "manual_nav_override" not in st.session_state:
    st.session_state.manual_nav_override = None
if "data_source" not in st.session_state:
    st.session_state.data_source = "未知"


def load_state():
    """加载状态文件"""
    try:
        if os.path.exists("state.json"):
            with open("state.json", "r", encoding="utf-8") as f:
                state = json.load(f)
                st.session_state.reserve_balance = state.get("reserve_balance", 0.0)
                st.session_state.last_signal_date = state.get("last_signal_date")
                return state
    except Exception as e:
        st.warning(f"状态文件加载失败: {e}")

    return {"reserve_balance": 0.0, "last_signal_date": None}


def save_state():
    """保存状态到文件"""
    try:
        state = {
            "reserve_balance": st.session_state.reserve_balance,
            "last_signal_date": st.session_state.last_signal_date,
            "last_update": datetime.now().isoformat(),
        }
        with open("state.json", "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        st.error(f"状态保存失败: {e}")
        return False


def get_fund_data(config, manual_nav=None):
    """获取基金数据"""
    try:
        # 获取基金净值
        nav, source, status = get_latest_nav_with_fallback(
            config["fund_code"], config["fund_name_en"], manual_nav
        )
        st.session_state.data_source = source

        if nav is None:
            st.error(f"无法获取基金净值: {status}")
            return None, None, None

        # 获取指数数据
        df, index_source, index_status = get_index_data_with_fallback(
            config["proxy_index"], f"{config['proxy_index']}.SZ"
        )

        return nav, df, index_source

    except Exception as e:
        st.error(f"数据获取失败: {e}")
        return None, None, None


def calculate_all_signals(config, nav, df):
    """计算所有信号"""
    try:
        # 计算MA200偏离
        deviation_info = calculate_ma200_deviation(df, nav)

        # 计算定投分配
        state = {
            "reserve_balance": st.session_state.reserve_balance,
            "last_signal_date": st.session_state.last_signal_date,
        }

        allocation = calculate_dca_allocation(config, state, deviation_info)

        # 计算MA200趋势
        trend_info = calculate_ma200_trend(df)

        # 获取买点信号
        buy_signals = get_buy_signals(df)

        return deviation_info, allocation, trend_info, buy_signals

    except Exception as e:
        st.error(f"信号计算失败: {e}")
        return None, None, None, None


def main_page(config, nav, deviation_info, allocation, holdings_summary):
    """主页面"""
    st.title("🏠 投资仪表盘")

    # 四个指标卡
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "当前净值", f"¥{nav:.4f}", help=f"数据源: {st.session_state.data_source}"
        )

    with col2:
        st.metric(
            "持仓市值",
            format_currency(holdings_summary["market_value"]),
            help="按当前净值计算的持仓市值",
        )

    with col3:
        st.metric(
            "持有收益",
            format_currency(holdings_summary["unrealized_pnl"]),
            delta=f"{holdings_summary['unrealized_pct']:.2f}%",
            delta_color=(
                "inverse" if holdings_summary["unrealized_pnl"] < 0 else "normal"
            ),
            help="未实现盈亏及收益率",
        )

    with col4:
        st.metric(
            "累计盈亏",
            format_currency(holdings_summary["total_pnl"]),
            delta=(
                f"{holdings_summary['total_pct']:.2f}%"
                if "total_pct" in holdings_summary
                else None
            ),
            delta_color="inverse" if holdings_summary["total_pnl"] < 0 else "normal",
            help="包含已实现的累计盈亏",
        )

    # 使用Tabs组织内容
    tab1, tab2, tab3, tab4 = st.tabs(
        ["📊 信号&建议", "📋 持仓明细", "📈 指数走势", "📝 系统日志"]
    )

    with tab1:
        st.subheader("📊 投资信号与建议")

        # 估值分析
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("MA200偏离", f"{deviation_info['deviation_pct']:.2f}%")
        with col2:
            level_colors = {"low": "🟢", "mid": "🟡", "high": "🔴"}
            st.metric(
                "估值水平",
                f"{level_colors[deviation_info['level']]} {deviation_info['level'].upper()}",
            )
        with col3:
            st.metric("动态投比例", f"{allocation['alloc_ratio']:.1%}")

        # 定投建议
        st.subheader("💰 本周定投建议")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("固定定投", format_currency(allocation["fixed_amount"]))
        with col2:
            st.metric("动态定投", format_currency(allocation["dynamic_amount"]))
        with col3:
            st.metric(
                "总定投金额",
                format_currency(allocation["total_amount"]),
                delta=f"{(allocation['total_amount']/allocation['weekly_budget']-1)*100:.1f}%",
            )

    with tab2:
        st.subheader("📋 持仓明细")
        # 持仓表格
        holdings_calculator = HoldingsCalculator(config)
        holdings_df = holdings_calculator.generate_holdings_df(holdings_summary)
        st.dataframe(holdings_df, use_container_width=True)

        # 导出按钮
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📥 导出CSV"):
                csv = holdings_df.to_csv(index=False)
                st.download_button(
                    label="下载持仓明细",
                    data=csv,
                    file_name="holdings_export.csv",
                    mime="text/csv",
                )

    with tab3:
        st.subheader("📈 指数走势分析")
        # 这里可以添加指数走势图表
        st.info("指数走势图表功能开发中...")

    with tab4:
        st.subheader("📝 系统日志")
        st.info("系统运行日志功能开发中...")

    # 刷新按钮
    if st.button("🔄 刷新数据", type="primary"):
        st.rerun()

    # 数据源状态
    data_status = get_data_source_status()
    st.info(
        f"📡 数据源状态: AKShare({'✓' if data_status['akshare'] else '✗'}) | "
        f"YFinance({'✓' if data_status['yfinance'] else '✗'}) | "
        f"当前使用: {st.session_state.data_source}"
    )


def dca_advice_page(config, allocation, deviation_info):
    """定投建议页面"""
    st.title("💰 定投建议")

    # 本周定投建议
    st.subheader("📊 本周定投建议")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("固定定投", format_currency(allocation["fixed_amount"]))

    with col2:
        st.metric("动态定投", format_currency(allocation["dynamic_amount"]))

    with col3:
        st.metric(
            "总定投金额",
            format_currency(allocation["total_amount"]),
            delta=f"{(allocation['total_amount']/allocation['weekly_budget']-1)*100:.1f}%",
        )

    # 定投计划表格
    st.subheader("📋 定投计划明细")
    plan_df = generate_dca_plan_df(allocation)
    st.dataframe(plan_df, use_container_width=True)

    # 估值信息
    st.subheader("📈 估值分析")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("MA200偏离", f"{deviation_info['deviation_pct']:.2f}%")

    with col2:
        level_colors = {"low": "🟢", "mid": "🟡", "high": "🔴"}
        st.metric(
            "估值水平",
            f"{level_colors[deviation_info['level']]} {deviation_info['level'].upper()}",
        )

    with col3:
        st.metric("动态投比例", f"{allocation['alloc_ratio']:.1%}")

    # 准备金信息
    st.subheader("🏦 准备金管理")

    col1, col2 = st.columns(2)

    with col1:
        st.metric("准备金余额", format_currency(allocation["reserve_before"]))

    with col2:
        st.metric("使用后余额", format_currency(allocation["reserve_after"]))

    # 可执行指令
    st.subheader("🎯 执行建议")

    if allocation["total_amount"] > 0:
        st.success(f"**本周建议申购: ¥{allocation['total_amount']:.2f}**")
        st.info(
            f"其中固定定投 ¥{allocation['fixed_amount']:.2f}，"
            f"动态定投 ¥{allocation['dynamic_amount']:.2f}"
        )
    else:
        st.warning("本周无需定投")


def valuation_page(config, df, deviation_info, trend_info, buy_signals):
    """估值与买点页面"""
    st.title("📊 估值 & 买点")

    # MA200趋势图
    st.subheader("📈 MA200 趋势分析")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("趋势方向", trend_info["trend"])

    with col2:
        st.metric("30天变化", f"{trend_info['change_pct']:.2f}%")

    with col3:
        st.metric("当前偏离", f"{deviation_info['deviation_pct']:.2f}%")

    # 绘制MA200图表
    if not df.empty:
        fig = go.Figure()

        # 收盘价
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["close"],
                mode="lines",
                name="收盘价",
                line=dict(color="#1f77b4", width=2),
            )
        )

        # MA200
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["ma200"],
                mode="lines",
                name="MA200",
                line=dict(color="#ff7f0e", width=2, dash="dash"),
            )
        )

        # 买点标记
        if not buy_signals.empty:
            fig.add_trace(
                go.Scatter(
                    x=buy_signals["date"],
                    y=buy_signals["close"],
                    mode="markers",
                    name="买点信号",
                    marker=dict(color="red", size=8, symbol="triangle-up"),
                )
            )

        # 添加估值背景带
        latest_close = df["close"].iloc[-1]
        latest_ma200 = df["ma200"].iloc[-1]

        # 定义估值带（基于MA200的偏离程度）
        low_band = [latest_ma200 * 0.85, latest_ma200 * 0.95]  # 低估带
        high_band = [latest_ma200 * 1.05, latest_ma200 * 1.15]  # 高估带

        # 添加低估区域背景
        fig.add_hrect(
            y0=low_band[0],
            y1=low_band[1],
            fillcolor="green",
            opacity=0.1,
            annotation_text="低估区域",
            annotation_position="bottom left",
        )

        # 添加高估区域背景
        fig.add_hrect(
            y0=high_band[0],
            y1=high_band[1],
            fillcolor="red",
            opacity=0.1,
            annotation_text="高估区域",
            annotation_position="top left",
        )

        # 添加当前价格水平线
        fig.add_hline(
            y=latest_close,
            line_dash="dot",
            line_color="blue",
            opacity=0.5,
            annotation_text=f"当前价格: {latest_close:.2f}",
            annotation_position="top right",
        )

        fig.update_layout(
            title="指数价格与MA200趋势分析",
            xaxis_title="日期",
            yaxis_title="价格",
            hovermode="x unified",
            height=500,
            # 使用配置文件中的颜色
            plot_bgcolor="#262730",
            paper_bgcolor="#0e1117",
            font=dict(color="#fafafa"),
        )

        st.plotly_chart(fig, use_container_width=True)

    # 买点信号表格
    if not buy_signals.empty:
        st.subheader("🎯 买点信号")
        st.dataframe(buy_signals, use_container_width=True)
    else:
        st.info("当前无买点信号")


def holdings_page(config, holdings_summary, holdings_calculator):
    """持仓明细页面"""
    st.title("💼 持仓明细")

    if holdings_summary["status"] == "无持仓":
        st.warning("当前无持仓")
        return

    # 持仓概览
    st.subheader("📊 持仓概览")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("持有份额", f"{holdings_summary['units']:.4f}")

    with col2:
        st.metric("平均成本", format_currency(holdings_summary["avg_cost"], 4))

    with col3:
        st.metric("盈亏平衡净值", format_currency(holdings_summary["breakeven_nav"], 4))

    with col4:
        st.metric(
            "距离盈亏平衡",
            f"{((holdings_summary['breakeven_nav'] - holdings_summary['current_nav']) / holdings_summary['current_nav']) * 100:.2f}%",
        )

    # 持仓明细表格
    st.subheader("📋 持仓明细")
    holdings_df = holdings_calculator.generate_holdings_df(holdings_summary)
    st.dataframe(holdings_df, use_container_width=True)

    # ROI指标
    st.subheader("📈 ROI指标")
    roi_metrics = holdings_calculator.calculate_roi_metrics(holdings_summary)

    if roi_metrics:
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("未实现ROI", f"{roi_metrics['unrealized_roi']:.2f}%")

        with col2:
            st.metric("累计ROI", f"{roi_metrics['total_roi']:.2f}%")

        with col3:
            st.metric("夏普比率", f"{roi_metrics['sharpe_ratio']:.3f}")
            st.caption("夏普比率（简化估算，仅供参考）")

        with col4:
            st.metric("盈亏平衡ROI", f"{roi_metrics['breakeven_roi']:.2f}%")

    # 导出功能
    st.subheader("📤 数据导出")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("导出持仓CSV"):
            filename = holdings_calculator.export_holdings_csv(holdings_summary)
            if filename:
                st.success(f"已导出到: {filename}")

    with col2:
        if st.button("导出持仓PNG"):
            # 这里可以实现图表导出功能
            st.info("图表导出功能开发中...")


def sidebar_controls():
    """侧边栏控制"""
    st.sidebar.title("⚙️ 控制面板")

    # 手动净值输入
    manual_nav = st.sidebar.text_input(
        "手动净值覆盖",
        value=st.session_state.manual_nav_override or "",
        help="留空则自动获取，输入数值则使用手动值",
    )

    if manual_nav:
        try:
            st.session_state.manual_nav_override = float(manual_nav)
        except ValueError:
            st.sidebar.error("请输入有效的数值")
            st.session_state.manual_nav_override = None

    # 清除手动净值
    if st.sidebar.button("清除手动净值"):
        st.session_state.manual_nav_override = None
        st.rerun()

    st.sidebar.divider()

    # 数据源状态
    st.sidebar.subheader("📡 数据源状态")
    data_status = get_data_source_status()

    for source, available in data_status.items():
        status_icon = "✅" if available else "❌"
        st.sidebar.text(f"{status_icon} {source.upper()}")

    st.sidebar.divider()

    # 当前数据源
    st.sidebar.subheader("🔍 当前数据源")
    st.sidebar.text(f"净值: {st.session_state.data_source}")

    # 清除缓存
    if st.sidebar.button("🗑️ 清除缓存"):
        st.cache_data.clear()
        st.success("缓存已清除")


# 数据读取函数
@st.cache_data(ttl=600)
def load_table_v2(name: str, fund_code: str | None = None):
    con = sqlite3.connect(DB_PATH)
    try:
        if fund_code and name.endswith("_v2"):
            df = pd.read_sql(
                f"SELECT * FROM {name} WHERE fund_code=?",
                con,
                params=[fund_code],
                parse_dates=["date"],
            )
        else:
            df = pd.read_sql(f"SELECT * FROM {name}", con, parse_dates=["date"])
        return df.sort_values("date")
    finally:
        con.close()


# 总览页面
def portfolio_overview():
    rows = []
    for f in funds:
        code = f["fund_code"]
        plan = load_table_v2("dca_plan_v2", code).tail(1)
        proxy = load_table_v2("proxy_daily_v2", code).tail(1)
        nav = load_table_v2("nav_daily_v2", code).tail(1)
        if plan.empty or proxy.empty or nav.empty:
            continue
        rows.append(
            {
                "基金": f"{code} {f['fund_name']}",
                "最新净值": nav["nav"].iloc[-1],
                "估值偏离(%)": proxy["dev_pct"].iloc[-1],
                "估值层级": plan["level"].iloc[-1].upper(),
                "本周建议(¥)": plan["total_amt"].iloc[-1],
                "固定(¥)": plan["base_amt"].iloc[-1],
                "动态(¥)": plan["dyn_amt"].iloc[-1],
                "准备金余(¥)": plan["reserve_after"].iloc[-1],
                "数据日期": plan["date"].iloc[-1],
            }
        )
    if rows:
        df = pd.DataFrame(rows).sort_values("估值偏离(%)")
        st.subheader("📊 组合总览")
        st.dataframe(df, use_container_width=True)
        st.caption("提示：偏离越负→越低估；建议金额含固定+动态。")
    else:
        st.info("暂无数据，先运行一次 daily_run 或点击下方按钮。")


# 单基金页面（保留原有 4 个 Tab）
def single_fund_view(fund_code):
    fund = FUND_MAP[fund_code]
    st.title(f"{fund['fund_name']} ({fund_code})")

    # 仪表盘部分
    st.subheader("📊 仪表盘 - 关键指标")
    nav_df = load_table_v2("nav_daily_v2", fund_code)
    if not nav_df.empty:
        latest_nav = nav_df.iloc[-1]["nav"]
        st.metric("最新净值", f"{latest_nav:.4f}")
    else:
        st.metric("最新净值", "暂无数据")
    # 添加更多仪表盘内容

    # 趋势部分
    st.subheader("📈 趋势图")
    proxy_df = load_table_v2("proxy_daily_v2", fund_code)
    if not proxy_df.empty:
        fig = px.line(proxy_df, x="date", y=["close", "ma200"], title="指数与MA200趋势")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无趋势数据")

    # 计划部分
    st.subheader("🧭 定投计划")
    plan_df = load_table_v2("dca_plan_v2", fund_code)
    if not plan_df.empty:
        latest_plan = plan_df.iloc[-1]
        st.write(
            f"当前定投计划 - 层级: {latest_plan['level']}, 总金额: {format_currency(latest_plan['total_amt'])}"
        )

        # 准备金变化折线图
        st.subheader("准备金变化")
        fig_reserve = px.line(
            plan_df, x="date", y="reserve_after", title="准备金余额变化"
        )
        st.plotly_chart(fig_reserve, use_container_width=True)
    else:
        st.info("暂无定投计划数据")

    # 日志部分
    st.subheader("📜 交易日志")
    # 这里可以添加交易日志内容
    st.info("暂无交易日志数据")


# 主页面逻辑
def main():
    if selected_code == "(全部)":
        portfolio_overview()
    else:
        single_fund_view(selected_code)


if __name__ == "__main__":
    main()
