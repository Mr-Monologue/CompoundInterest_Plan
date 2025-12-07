from sqlmodel import Session, select

from db.models import Asset, Transaction

from services.market import get_strategy_advice

from services.strategy import calculate_grid_logic

from db.state import get_global_state


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
    candidates = []

    # === 第 1 轮：算总市值 ===
    total_market_value = 0.0

    for asset in assets:
        mdata = get_strategy_advice(asset.code, asset.name)
        if mdata.get("action") == "ERROR":
            continue

        # 1. 查持仓份额
        txs = session.exec(
            select(Transaction).where(Transaction.asset_code == asset.code)
        ).all()
        units = sum(t.units for t in txs if t.type == "BUY") - sum(
            t.units for t in txs if t.type == "SELL"
        )

        # 2. 算当前市值
        current_mv = units * mdata["current_price"]
        total_market_value += current_mv

        # 3. 算网格
        level, _, _, _, grid_pos, reason = calculate_grid_logic(
            mdata["current_price"], mdata["ma200"], mdata["vol_daily"], 0
        )

        candidates.append(
            {
                "asset": asset,
                "mdata": mdata,
                "grid_pos": grid_pos,
                "level": level,
                "current_mv": current_mv,
            }
        )

    # === 计算总资产净值 ===
    total_net_worth = total_market_value + current_pool
    if total_net_worth < 1000:
        total_net_worth = 1000

    # === 第 2 轮：排序 ===
    candidates.sort(key=lambda x: x["grid_pos"])

    # === 第 3 轮：生成建议清单 (带详细解释) ===
    suggestions = []
    sim_pool_balance = current_pool

    for item in candidates:
        asset = item["asset"]
        grid = item["grid_pos"]
        current_mv = item["current_mv"]

        # --- 基础计算 ---
        base_need = plan.base_investment
        multiplier = 1.0
        if grid <= -2.0:
            multiplier = 1.5 * (1.2 ** (abs(grid) - 2.0))
        elif grid > 0:
            multiplier = 1.0 - (grid * 0.5)

        # 原始建议金额 (未受限前)
        raw_target_amt = base_need * multiplier

        # --- 🚦 风控检查 ---
        current_weight = current_mv / total_net_worth
        max_weight = getattr(asset, "max_weight_limit", 0.2)

        brake_factor = 1.0
        brake_reason = ""

        if current_weight >= max_weight:
            brake_factor = 0.0
            # 🔥 解释：为什么不买？因为仓位爆了
            brake_reason = f"🚫 仓位({current_weight*100:.1f}%)超限({max_weight*100:.0f}%)，风控强制禁买"
        elif current_weight >= (max_weight * 0.8):
            ratio = 1.0 - (current_weight - max_weight * 0.8) / (max_weight * 0.2)
            brake_factor = max(0.0, ratio)
            # 🔥 解释：为什么买少了？因为快超限了
            brake_reason = f"⚠️ 仓位接近上限，买入打折 {brake_factor*100:.0f}%"

        # A. 如果被完全刹停
        if brake_factor == 0:
            suggestions.append(
                {
                    "code": asset.code,
                    "name": asset.name,
                    "amt": 0,
                    "msg": f"{brake_reason} (原计划投¥{raw_target_amt:.0f})",
                }
            )
            continue

        # B. 如果估值太高
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

        # C. 计算最终金额
        target_amt = raw_target_amt * brake_factor

        # 资金池模拟扣款
        actual_invest = min(target_amt, sim_pool_balance)

        # D. 财务门槛检查
        if actual_invest >= MIN_TRADE_AMOUNT:
            actual_invest = round(actual_invest / 10) * 10
            sim_pool_balance -= actual_invest

            # 正常买入文案
            msg = f"✅ 网格{grid:.1f}，建议买入"
            if brake_reason:
                msg = f"{msg} ({brake_reason})"  # 加上限流提示

            suggestions.append(
                {
                    "code": asset.code,
                    "name": asset.name,
                    "amt": actual_invest,
                    "msg": msg,
                }
            )
        elif actual_invest > 0:
            # 🔥 解释：为什么有钱但不买？因为太碎了
            suggestions.append(
                {
                    "code": asset.code,
                    "name": asset.name,
                    "amt": 0,
                    "msg": f"👛 建议额¥{actual_invest:.0f} 低于起投门槛(¥{MIN_TRADE_AMOUNT})，暂攒着",
                }
            )
        else:
            suggestions.append(
                {"code": asset.code, "name": asset.name, "amt": 0, "msg": "无需操作"}
            )

    return {"suggestions": suggestions, "pool_remain_sim": sim_pool_balance}
