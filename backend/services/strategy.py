from sqlmodel import Session, select
from datetime import date, datetime
from db.models import FundState, DailyPlan
from services.market import get_strategy_advice
import math

# === 你的策略参数 ===
WEEKLY_BUDGET = 200.0
MAX_SINGLE_MULTIPLIER = 5.0  # 单次最大5倍


def calculate_grid_logic(current_price, ma200, vol_daily, reserve_balance):
    """
    🧠 核心算法 v2.1 (优化版)：线性插值 + 几何网格
    """
    if ma200 <= 0:
        return "mid", 0, 0, 0, 0, "数据不足", 0

    # 1. 计算网格宽度
    vol_weekly = vol_daily * 2.236
    grid_width = max(vol_weekly * 0.6, 0.005)  # 最小0.5%防止分母过小

    # 2. 计算网格位置
    deviation = (current_price - ma200) / ma200
    grid_pos = deviation / grid_width

    # 3. 决策逻辑
    base_amt = WEEKLY_BUDGET
    final_invest = 0.0
    to_reserve = 0.0
    from_reserve = 0.0
    level = "mid"
    reasons = []

    # === A. 高估区 (Position > 2.0) ===
    if grid_pos >= 2.0:
        level = "high"
        to_reserve = base_amt
        final_invest = 0
        reasons.append(f"高估{grid_pos:.1f}格，暂停定投，全额蓄力")

    # === B. 正常震荡 (-2.0 < Position < 2.0) ===
    elif grid_pos > -2.0:
        level = "mid"

        # 🔥 优化点：线性插值，拒绝硬切 🔥
        # 逻辑：
        # 网格 < 0 (均线以下): 保持 100% 定投 (200元)
        # 网格 0 -> 2 (均线以上): 比例从 100% 线性降至 0%

        if grid_pos <= 0:
            ratio = 1.0
            reasons.append(f"中低区({grid_pos:.1f}格)，标准定投")
        else:
            # grid_pos 在 0~2 之间
            # 0 -> 1.0, 1 -> 0.5, 2 -> 0.0
            ratio = 1.0 - (grid_pos * 0.5)
            ratio = max(0.0, ratio)  # 兜底不小于0
            reasons.append(f"中高区({grid_pos:.1f}格)，投入收缩至{ratio*100:.0f}%")

        final_invest = base_amt * ratio
        to_reserve = base_amt - final_invest  # 剩下的存起来

    # === C. 低估区 (Position < -2.0) ===
    else:
        level = "low"
        # 几何倍数公式：1.5 * (1.2 ^ 超跌格数)
        extra_grids = abs(grid_pos) - 2.0
        multiplier = 1.5 * (1.2**extra_grids)

        # 硬上限
        if multiplier > MAX_SINGLE_MULTIPLIER:
            multiplier = MAX_SINGLE_MULTIPLIER
            reasons.append("触及单次倍数上限")

        target_amt = base_amt * multiplier

        # 资金分配
        if target_amt <= base_amt:
            final_invest = target_amt
        else:
            final_invest = target_amt
            needed_extra = target_amt - base_amt
            if needed_extra <= reserve_balance:
                from_reserve = needed_extra
                reasons.append(f"低估{grid_pos:.1f}格，{multiplier:.1f}倍加码")
            else:
                from_reserve = reserve_balance
                final_invest = base_amt + from_reserve
                reasons.append(f"低估{grid_pos:.1f}格，弹药耗尽全力买入")

    return level, final_invest, to_reserve, from_reserve, grid_pos, ", ".join(reasons)


def get_instant_analysis(code: str, session: Session):
    # ... (保持不变，但为了防止你复制漏，这里完整写一遍) ...
    mdata = get_strategy_advice(code)
    if mdata.get("action") == "ERROR":
        return mdata

    state = get_or_create_state(session, code)

    level, invest, _, _, grid_pos, reason = calculate_grid_logic(
        mdata["current_price"],
        mdata["ma200"],
        mdata["vol_daily"],
        state.reserve_balance,
    )

    action_str = "BUY" if invest > 0 else "SELL"
    if level == "high":
        action_str = "WAIT"

    mdata.update(
        {
            "action": action_str,
            "suggested_amount": round(invest, 0),
            "reason": f"网格: {grid_pos:.1f} ({reason})",
            "grid_pos": grid_pos,
        }
    )
    return mdata


def run_strategy_analysis(code: str, session: Session):
    # 1. 获取数据
    mdata = get_strategy_advice(code)
    if mdata.get("action") == "ERROR":
        raise Exception(mdata.get("reason"))

    # 2. 获取状态
    state = get_or_create_state(session, code)

    # 3. 计算
    level, invest, to_res, from_res, grid_pos, reason = calculate_grid_logic(
        mdata["current_price"],
        mdata["ma200"],
        mdata["vol_daily"],
        state.reserve_balance,
    )

    # 4. 更新数据库
    new_reserve = state.reserve_balance + to_res - from_res
    today_str = date.today().isoformat()

    # 删旧记录
    existing = session.exec(
        select(DailyPlan).where(
            DailyPlan.asset_code == code, DailyPlan.date == today_str
        )
    ).first()
    if existing:
        session.delete(existing)

    plan = DailyPlan(
        asset_code=code,
        date=today_str,
        close=mdata["current_price"],
        ma200=mdata["ma200"],
        dev_pct=grid_pos,
        level=level,
        base_amt=WEEKLY_BUDGET,
        dyn_amt=from_res if from_res > 0 else -to_res,  # 正=取, 负=存
        total_amt=invest,
        reserve_before=state.reserve_balance,
        reserve_after=new_reserve,
    )
    session.add(plan)

    state.reserve_balance = new_reserve
    state.last_signal_date = today_str
    session.add(state)
    session.commit()

    return {
        "date": today_str,
        "level": level,
        "grid_pos": f"{grid_pos:.1f}",
        "advice": f"建议买入 ¥{invest:.0f}",
        "details": reason,
        "reserve_balance": new_reserve,
    }


def get_or_create_state(session: Session, code: str):
    state = session.exec(select(FundState).where(FundState.asset_code == code)).first()
    if not state:
        state = FundState(asset_code=code, reserve_balance=0.0)
        session.add(state)
        session.commit()
        session.refresh(state)
    return state


def generate_weekly_report_text(code: str, session: Session, days: int = 7):
    plans = session.exec(
        select(DailyPlan)
        .where(DailyPlan.asset_code == code)
        .order_by(DailyPlan.date.desc())
        .limit(days)
    ).all()
    if not plans:
        return "无数据"
    plans = plans[::-1]
    last = plans[-1]

    # 🔥 优化点：文案逻辑重写，清晰展示资金流向 🔥
    action_desc = ""
    if last.total_amt == 0:
        action_desc = f"🛑 暂停定投，本周预算 ¥{abs(last.dyn_amt):.0f} 存入准备金"
    elif last.dyn_amt > 0:
        action_desc = (
            f"🚀 加码定投 ¥{last.total_amt:.0f} (含备用金 ¥{last.dyn_amt:.0f})"
        )
    elif last.dyn_amt < 0:
        # 这种情况是：买了一部分，存了一部分
        saved = abs(last.dyn_amt)
        action_desc = f"⚖️ 减额定投 ¥{last.total_amt:.0f} (结余 ¥{saved:.0f} 存入准备金)"
    else:
        action_desc = f"✅ 标准定投 ¥{last.total_amt:.0f}"

    return f"""
**[{code}] 策略复盘 ({plans[0].date} ~ {last.date})**
-------------------
📊 **网格位置**：{last.dev_pct:.1f} 格
💰 **本周投入**：¥{last.total_amt:.0f}
📝 **执行动作**：{action_desc}
🏦 **准备金池**：¥{last.reserve_after:.0f}
    """
