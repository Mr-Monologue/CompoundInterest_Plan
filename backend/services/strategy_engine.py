from sqlmodel import Session, select
from datetime import date, datetime
from db.models import Asset, FundState, DailyPlan
from services.market import get_strategy_advice  # 复用我们之前写好的行情获取

# === 核心配置 ===
WEEKLY_BUDGET = 1000  # 每周基础预算 (可改为从数据库读取)


def get_or_create_state(session: Session, code: str):
    """获取基金状态，没有则创建"""
    state = session.exec(select(FundState).where(FundState.asset_code == code)).first()
    if not state:
        state = FundState(asset_code=code, reserve_balance=0.0)
        session.add(state)
        session.commit()
        session.refresh(state)
    return state


def calculate_dca(dev_pct: float, reserve_balance: float):
    """
    🔥 核心策略算法 (请在此处还原你的公式)
    输入: 偏离度, 当前准备金
    输出: 级别, 固定投入, 动态投入, 新的准备金
    """
    base_amt = WEEKLY_BUDGET
    dyn_amt = 0.0
    level = "mid"
    new_reserve = reserve_balance

    # --- 你的策略逻辑 ---
    if dev_pct < -0.20:  # 极度低估
        level = "low"
        # 假设逻辑: 动用一半准备金 + 双倍定投
        dyn_amt = min(reserve_balance, base_amt)
        new_reserve -= dyn_amt
        base_amt = base_amt * 2  # 甚至更多

    elif dev_pct < 0:  # 低估
        level = "low"
        dyn_amt = 0
        # 正常定投

    elif dev_pct > 0.10:  # 高估
        level = "high"
        # 减少投入，存入准备金
        saved_money = base_amt * 0.5
        base_amt = base_amt * 0.5
        new_reserve += saved_money

    else:  # 正常
        level = "mid"
        # 正常定投
    # ------------------

    return level, base_amt, dyn_amt, new_reserve


def run_daily_analysis(code: str, session: Session):
    """
    执行每日分析：获取行情 -> 计算策略 -> 更新数据库 -> 返回结果
    """
    # 1. 获取行情 (复用之前的逻辑)
    market_data = get_strategy_advice(code)
    if market_data["action"] == "ERROR":
        raise Exception(market_data["reason"])

    # 2. 获取当前状态 (准备金)
    state = get_or_create_state(session, code)

    # 3. 计算策略
    dev_pct = market_data["deviation"] / 100.0  # 转为小数
    level, base_amt, dyn_amt, new_reserve = calculate_dca(
        dev_pct, state.reserve_balance
    )

    total_amt = base_amt + dyn_amt
    today_str = date.today().isoformat()

    # 4. 记录历史 (DailyPlan)
    # 检查今天是否已经跑过，防止重复插入
    existing_plan = session.exec(
        select(DailyPlan).where(
            DailyPlan.asset_code == code, DailyPlan.date == today_str
        )
    ).first()

    if not existing_plan:
        plan = DailyPlan(
            asset_code=code,
            date=today_str,
            nav=market_data["current_price"],
            ma200=market_data["ma200"],
            dev_pct=dev_pct,
            level=level,
            base_amt=base_amt,
            dyn_amt=dyn_amt,
            total_amt=total_amt,
            reserve_before=state.reserve_balance,
            reserve_after=new_reserve,
        )
        session.add(plan)

        # 5. 更新状态 (FundState)
        state.reserve_balance = new_reserve
        state.last_signal_date = today_str
        state.updated_at = datetime.now()
        session.add(state)

        session.commit()
    else:
        plan = existing_plan

    return {
        "date": today_str,
        "level": level,
        "advice": f"固定 {base_amt} + 动态 {dyn_amt} (总计 {total_amt})",
        "reserve_change": f"{state.reserve_balance:.2f} -> {new_reserve:.2f}",
    }


def generate_weekly_report(code: str, session: Session, days: int = 7):
    """生成周复盘文案"""

    # 1. 查询最近 N 天的记录
    plans = session.exec(
        select(DailyPlan)
        .where(DailyPlan.asset_code == code)
        .order_by(DailyPlan.date.desc())
        .limit(days)
    ).all()

    # 如果倒序出来的，翻转一下变成时间正序
    plans = plans[::-1]

    if not plans:
        return f"[{code}] 最近 {days} 天无策略记录，请先执行分析。"

    # 2. 统计数据
    total_amt = sum(p.total_amt for p in plans)
    base_sum = sum(p.base_amt for p in plans)
    dyn_sum = sum(p.dyn_amt for p in plans)

    low_days = sum(1 for p in plans if p.level == "low")
    mid_days = sum(1 for p in plans if p.level == "mid")
    high_days = sum(1 for p in plans if p.level == "high")

    avg_dev = sum(p.dev_pct for p in plans) / len(plans)

    last_plan = plans[-1]
    start_date = plans[0].date
    end_date = last_plan.date

    # 3. 生成建议文案
    advice_text = ""
    if last_plan.level == "low":
        advice_text = "当前估值偏低，系统建议加大投入，积极动用准备金。"
    elif last_plan.level == "high":
        advice_text = "当前估值偏高，建议减少投入，积累子弹。"
    else:
        advice_text = "当前估值合理，维持标准定投节奏。"

    # 4. 组合最终文本
    report = f"""
**【{code}】策略复盘 ({start_date} ~ {end_date})**

------------------------------
📊 **估值分布**：低估 {low_days}天 / 合理 {mid_days}天 / 高估 {high_days}天
📈 **偏离度**：平均 {avg_dev*100:.2f}%
💰 **资金投入**：共 ¥{total_amt:.0f} (固定 ¥{base_sum:.0f} + 动态 ¥{dyn_sum:.0f})
🏦 **准备金**：当前余额 ¥{last_plan.reserve_after:.2f}

💡 **最新建议**：{advice_text}
"""

    return report
