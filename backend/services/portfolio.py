from sqlmodel import Session, select

from db.models import Asset, Transaction, IndustryLimit

from services.market import get_strategy_advice

from services.strategy import calculate_grid_logic

from db.state import get_global_state

from services.holdings import get_fund_industry_vector  # 引入新工具

from collections import defaultdict


# === ⚙️ 交易参数 ===
MIN_TRADE_AMOUNT = 50.0
DEFAULT_BUY_FEE = 0.0015


# === 新增：资金池充值/提现 ===
def adjust_pool_balance(session: Session, amount: float, operation: str = "DEPOSIT"):
    state = get_global_state(session)
    if operation == "DEPOSIT":
        state.pool_balance += amount
    elif operation == "WITHDRAW":
        state.pool_balance -= amount

    session.add(state)
    session.commit()
    session.refresh(state)
    return state


def run_portfolio_strategy(session: Session):
    plan = get_global_state(session)
    current_pool = plan.pool_balance
    assets = session.exec(select(Asset)).all()

    # 预加载行业限额配置
    industry_limits_db = session.exec(select(IndustryLimit)).all()
    industry_limits = {il.industry: il.max_weight for il in industry_limits_db}

    # 默认行业限额 30%
    def get_ind_limit(ind):
        return industry_limits.get(ind, 0.3)

    candidates = []
    total_market_value = 0.0

    # === 🔥 新增：全局行业市值统计 🔥 ===
    global_industry_mv = defaultdict(float)

    # === 第 1 轮：收集数据 & 算底仓 ===
    for asset in assets:
        mdata = get_strategy_advice(asset.code, asset.name)
        if mdata.get("action") == "ERROR":
            continue

        # 1. 算单只基金市值
        txs = session.exec(
            select(Transaction).where(Transaction.asset_code == asset.code)
        ).all()
        units = sum(t.units for t in txs if t.type == "BUY") - sum(
            t.units for t in txs if t.type == "SELL"
        )
        current_mv = units * mdata["current_price"]
        total_market_value += current_mv

        # 2. 🔥 穿透计算行业市值 🔥
        # 获取该基金的行业分布 (例如: {医药: 0.8, 消费: 0.1})
        ind_vector = get_fund_industry_vector(session, asset.code)

        if ind_vector:
            for ind, weight in ind_vector.items():
                # 基金市值 * 行业占比 = 该行业贡献的市值
                global_industry_mv[ind] += current_mv * weight
        else:
            # 如果没有穿透数据，暂时归入"未知/基金本身类型"
            # 这里可以做一个简单映射，或者暂时忽略
            pass

        # 3. 算网格
        level, _, _, _, grid_pos, _ = calculate_grid_logic(
            mdata["current_price"], mdata["ma200"], mdata["vol_daily"], 0
        )

        candidates.append(
            {
                "asset": asset,
                "mdata": mdata,
                "grid_pos": grid_pos,
                "current_mv": current_mv,
                "ind_vector": ind_vector,
            }
        )

    # === 计算总资产 ===
    total_net_worth = total_market_value + current_pool
    if total_net_worth < 1000:
        total_net_worth = 1000

    # === 排序 ===
    candidates.sort(key=lambda x: x["grid_pos"])

    suggestions = []
    sim_pool_balance = current_pool

    # === 第 2 轮：决策分配 (双重刹车) ===
    for item in candidates:
        asset = item["asset"]
        grid = item["grid_pos"]
        current_mv = item["current_mv"]
        ind_vector = item.get("ind_vector")

        brake_factor = 1.0
        brake_reasons = []

        # --- 🚦 刹车 1: 单标的仓位 ---
        current_weight = current_mv / total_net_worth
        max_weight = getattr(asset, "max_weight_limit", 0.2)

        if current_weight >= max_weight:
            brake_factor = 0.0
            brake_reasons.append(f"单标仓位({current_weight*100:.1f}%)超限")
        elif current_weight >= (max_weight * 0.8):
            ratio = 1.0 - (current_weight - max_weight * 0.8) / (max_weight * 0.2)
            brake_factor = min(brake_factor, ratio)
            brake_reasons.append(f"单标接近上限")

        # --- 🚦 刹车 2: 行业穿透限额 ---
        if ind_vector and brake_factor > 0:
            for ind, w in ind_vector.items():
                # 该行业当前的全局市值
                ind_mv = global_industry_mv.get(ind, 0.0)
                ind_ratio = ind_mv / total_net_worth
                ind_limit = get_ind_limit(ind)

                # 如果这个基金买进去会让行业更超标，就要限制
                if ind_ratio >= ind_limit:
                    brake_factor = 0.0
                    brake_reasons.append(f"行业[{ind}]({ind_ratio*100:.1f}%)超限")
                    break  # 只要有一个行业爆了，整个基金就不能买
                elif ind_ratio >= ind_limit * 0.8:
                    # 行业也做线性减速
                    ratio = 1.0 - (ind_ratio - ind_limit * 0.8) / (ind_limit * 0.2)
                    brake_factor = min(brake_factor, ratio)
                    brake_reasons.append(f"行业[{ind}]接近上限")

        # 如果被刹停
        if brake_factor == 0:
            suggestions.append(
                {
                    "code": asset.code,
                    "name": asset.name,
                    "amt": 0,
                    "msg": f"🚫 禁买: {'; '.join(brake_reasons)}",
                }
            )
            continue

        # 如果估值太高
        if grid > 2.0:
            suggestions.append(
                {
                    "code": asset.code,
                    "name": asset.name,
                    "amt": 0,
                    "msg": f"📉 高估({grid:.1f}格)，建议观望",
                }
            )
            continue

        # 计算理论金额
        base_need = plan.base_investment
        multiplier = 1.0
        if grid <= -2.0:
            multiplier = 1.5 * (1.2 ** (abs(grid) - 2.0))
        elif grid > 0:
            multiplier = 1.0 - (grid * 0.5)

        target_amt = base_need * multiplier * brake_factor
        actual_invest = min(target_amt, sim_pool_balance)

        if actual_invest >= MIN_TRADE_AMOUNT:
            actual_invest = round(actual_invest / 10) * 10
            sim_pool_balance -= actual_invest

            msg = f"网格{grid:.1f}，建议买入"
            if brake_reasons:
                msg += f" (⚠️ {'; '.join(brake_reasons)})"

            suggestions.append(
                {
                    "code": asset.code,
                    "name": asset.name,
                    "amt": actual_invest,
                    "msg": msg,
                }
            )
        elif actual_invest > 0:
            suggestions.append(
                {
                    "code": asset.code,
                    "name": asset.name,
                    "amt": 0,
                    "msg": "金额不足起投",
                }
            )
        else:
            suggestions.append(
                {"code": asset.code, "name": asset.name, "amt": 0, "msg": "无需操作"}
            )

    return {"suggestions": suggestions, "pool_remain_sim": sim_pool_balance}
