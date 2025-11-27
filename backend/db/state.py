from sqlmodel import Session, select
from datetime import date, timedelta
from db.models import PlanState


# === 辅助：获取或初始化全局状态 ===
def get_global_state(session: Session):
    state = session.exec(select(PlanState).where(PlanState.id == 1)).first()
    if not state:
        # 初始化：假设本周从今天开始
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

    # 检查是否跨周 -> 重置预算
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    monday_str = monday.isoformat()

    if state.current_week_start != monday_str:
        print(f"📅 检测到新的一周 ({monday_str})，重置周预算...")
        state.current_week_start = monday_str
        state.budget_used_this_week = 0.0
        session.add(state)
        session.commit()
        session.refresh(state)

    return state
