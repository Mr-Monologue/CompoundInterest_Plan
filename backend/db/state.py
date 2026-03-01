from sqlmodel import Session, select
from db.models import PlanState


# === 辅助：获取或初始化全局状态 ===
def get_global_state(session: Session):
    state = session.exec(select(PlanState).where(PlanState.id == 1)).first()
    if not state:
        # 初始化默认值
        state = PlanState(
            id=1,
            pool_balance=0.0,  # 初始没钱
            base_investment=200.0,  # 默认每次基准投200
            deposit_frequency="MANUAL",
        )
        session.add(state)
        session.commit()
        session.refresh(state)

    return state
