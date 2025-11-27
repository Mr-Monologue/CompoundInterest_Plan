from sqlmodel import Session, select
from datetime import date, datetime, timedelta
from db.models import PlanState, FundState, Asset, Transaction, DailyPlan
from services.market import get_strategy_advice
from services.strategy import calculate_grid_logic

# === ⚙️ 交易参数配置 ===
MIN_TRADE_AMOUNT = 50.0  # 最小起投金额 (少于这个不买，攒着)
DEFAULT_BUY_FEE = 0.0015  # 默认申购费率 0.15% (支付宝/天天基金常用优惠费率)


def get_global_state(session: Session):
    state = session.exec(select(PlanState).where(PlanState.id == 1)).first()
    if not state:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        state = PlanState(
            id=1,
            weekly_budget=200.0,
            global_reserve=0.0,
            current_week_start=monday.isoformat(),
            budget_used_this_week=0.0,
        )
        session.add(state)
        session.commit()
        session.refresh(state)

    # 跨周重置
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    monday_str = monday.isoformat()
    if state.current_week_start != monday_str:
        state.current_week_start = monday_str
        state.budget_used_this_week = 0.0
        session.add(state)
        session.commit()
        session.refresh(state)
    return state


def run_portfolio_strategy(session: Session):
    plan = get_global_state(session)
    remaining_budget = plan.weekly_budget - plan.budget_used_this_week

    assets = session.exec(select(Asset)).all()
    candidates = []
    logs = []

    # 1. 收集所有标的的状态
    for asset in assets:
        mdata = get_strategy_advice(asset.code, asset.name)
        if mdata.get("action") == "ERROR":
            logs.append(f"❌ {asset.name}: 数据获取失败")
            continue

        level, _, _, _, grid_pos, reason = calculate_grid_logic(
            mdata["current_price"], mdata["ma200"], mdata["vol_daily"], 0
        )

        candidates.append(
            {"asset": asset, "mdata": mdata, "grid_pos": grid_pos, "level": level}
        )

    # 2. 按低估程度排序 (越低越优先)
    candidates.sort(key=lambda x: x["grid_pos"])

    total_invested_today = 0.0

    # 3. 分配资金
    for item in candidates:
        asset = item["asset"]
        grid = item["grid_pos"]
        mdata = item["mdata"]

        # 高估跳过
        if grid > 2.0:
            logs.append(f"📉 {asset.name}: 高估({grid:.1f})，跳过")
            continue

        # 计算理论应投金额
        base_need = 200.0
        multiplier = 1.0
        if grid <= -2.0:
            multiplier = 1.5 * (1.2 ** (abs(grid) - 2.0))
        elif grid > 0:
            multiplier = 1.0 - (grid * 0.5)

        target_amt = base_need * multiplier

        # 预计算资金来源 (尚未真正扣款)
        take_from_budget = 0.0
        take_from_reserve = 0.0

        # 先吃周预算
        if remaining_budget > 0:
            take_from_budget = min(target_amt, remaining_budget)
            target_amt -= take_from_budget

        # 不够吃准备金
        if target_amt > 0 and grid < -1.0 and plan.global_reserve > 0:
            take_from_reserve = min(target_amt, plan.global_reserve)

        final_invest = take_from_budget + take_from_reserve

        # === 🔥 核心修复：先判断门槛，再扣款 🔥 ===

        if final_invest >= MIN_TRADE_AMOUNT:
            # 取整
            final_invest = round(final_invest / 10) * 10

            # 资金来源分配 (保持不变)
            real_from_budget = min(final_invest, remaining_budget)
            real_from_reserve = final_invest - real_from_budget
            remaining_budget -= real_from_budget
            plan.global_reserve -= real_from_reserve

            # === 🔥 核心修改：费率计算逻辑 🔥 ===

            # 1. 区分 场内ETF(sh/sz) 和 场外基金(纯数字)
            is_otc = asset.code.isdigit()

            # 2. 设定费率
            # 场外基金：支付宝标准一折优惠 = 0.15% (0.0015)
            # 场内ETF：券商佣金通常万1~万3，这里按万2 (0.0002) 估算
            rate = 0.0015 if is_otc else 0.0002

            # 3. 应用支付宝官方公式：净金额 = 总金额 / (1 + 费率)
            net_amount = final_invest / (1 + rate)
            fee = final_invest - net_amount

            # 4. 记录交易
            _record_transaction(
                session,
                asset.code,
                "BUY",
                mdata["current_price"],
                final_invest,
                fee,
                net_amount,
            )

            total_invested_today += final_invest

            source_str = f"预算{real_from_budget:.0f}"
            if real_from_reserve > 0:
                source_str += f"+准备金{real_from_reserve:.0f}"
            logs.append(
                f"✅ {asset.name}: 投¥{final_invest} (费¥{fee:.2f}) [{source_str}]"
            )

        elif final_invest > 0:
            # 金额太小，被过滤，不扣钱！
            logs.append(
                f"⏸️ {asset.name}: 建议 ¥{final_invest:.1f} < 门槛{MIN_TRADE_AMOUNT}，忽略，资金保留"
            )
        else:
            logs.append(f"⏸️ {asset.name}: 无需买入")

    # 4. 更新全局状态
    # 用掉的预算 = 原始预算 - 现在的剩余
    plan.budget_used_this_week = plan.weekly_budget - remaining_budget

    session.add(plan)
    session.commit()

    return {
        "logs": logs,
        "global_status": {
            "budget_left": remaining_budget,
            "global_reserve": plan.global_reserve,
            "total_invested": total_invested_today,
        },
    }


def _record_transaction(session, code, type, price, total_amount, fee, net_amount):
    """
    记录交易
    total_amount: 总流出资金 (比如 1000)
    fee: 手续费 (比如 1.5)
    net_amount: 实际买入资产的钱 (998.5)
    """
    # 份额 = 净金额 / 单价
    units = net_amount / price

    tx = Transaction(
        asset_code=code,
        type=type,
        price=price,
        amount=total_amount,
        fee=fee,  # 记录手续费
        units=units,
        date=datetime.now(),
    )
    session.add(tx)
