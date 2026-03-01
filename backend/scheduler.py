"""
SmartInvest 自主调度器
- 每日策略执行（工作日收盘后自动运行全组合策略）
- 定期自动充值（按配置频率向资金池注资）
- 持仓同步（定期更新基金持仓数据）
"""

import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from db.database import engine
from db.models import Asset, PlanState
from db.state import get_global_state
from services.portfolio import run_portfolio_strategy, adjust_pool_balance
from services.strategy import run_strategy_analysis
from services.holdings import sync_fund_holdings

logger = logging.getLogger("smartinvest.scheduler")


class SmartInvestScheduler:
    def __init__(self):
        self._scheduler = BackgroundScheduler(
            timezone="Asia/Shanghai",
            job_defaults={"coalesce": True, "max_instances": 1},
        )
        self._setup_jobs()

    def _setup_jobs(self):
        # 每个工作日 15:30 执行全组合策略（A股收盘后）
        self._scheduler.add_job(
            self._job_daily_strategy,
            CronTrigger(day_of_week="mon-fri", hour=15, minute=30),
            id="daily_strategy",
            name="每日策略执行",
            replace_existing=True,
        )

        # 每周一 09:00 自动充值（如果配置了自动充值）
        self._scheduler.add_job(
            self._job_auto_deposit,
            CronTrigger(day_of_week="mon", hour=9, minute=0),
            id="weekly_deposit",
            name="每周自动充值",
            replace_existing=True,
        )

        # 每周日 02:00 同步全部基金持仓
        self._scheduler.add_job(
            self._job_sync_holdings,
            CronTrigger(day_of_week="sun", hour=2, minute=0),
            id="sync_holdings",
            name="持仓数据同步",
            replace_existing=True,
        )

    def start(self):
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("调度器已启动，定时任务已注册")

    def shutdown(self):
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("调度器已关闭")

    def is_running(self) -> bool:
        return self._scheduler.running

    def list_jobs(self) -> list:
        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "paused": job.next_run_time is None,
            })
        return jobs

    def trigger_job(self, job_id: str) -> bool:
        job = self._scheduler.get_job(job_id)
        if job:
            job.modify(next_run_time=datetime.now())
            return True
        return False

    def pause_job(self, job_id: str) -> bool:
        try:
            self._scheduler.pause_job(job_id)
            return True
        except Exception:
            return False

    def resume_job(self, job_id: str) -> bool:
        try:
            self._scheduler.resume_job(job_id)
            return True
        except Exception:
            return False

    # ==================
    #    定时任务实现
    # ==================

    def _job_daily_strategy(self):
        """每日策略：获取行情 → 计算网格 → 生成建议"""
        logger.info("=== [定时] 每日策略执行开始 ===")
        try:
            with Session(engine) as session:
                result = run_portfolio_strategy(session)
                suggestions = result.get("suggestions", [])
                pool_remain = result.get("pool_remain_sim", 0)

                for s in suggestions:
                    if s["amt"] > 0:
                        logger.info(f"  📈 {s['code']} {s['name']}: 建议买入 ¥{s['amt']:.0f} - {s['msg']}")
                    else:
                        logger.info(f"  ⏸️  {s['code']} {s['name']}: {s['msg']}")

                logger.info(f"  💰 资金池模拟剩余: ¥{pool_remain:.2f}")
                logger.info("=== [定时] 每日策略执行完成 ===")
        except Exception as e:
            logger.error(f"每日策略执行失败: {e}", exc_info=True)

    def _job_auto_deposit(self):
        """自动充值：按 PlanState 配置向资金池注资"""
        logger.info("=== [定时] 自动充值检查 ===")
        try:
            with Session(engine) as session:
                state = get_global_state(session)

                if state.deposit_frequency == "MANUAL":
                    logger.info("  充值模式: 手动，跳过自动充值")
                    return

                amount = state.auto_deposit_amount
                if amount <= 0:
                    logger.info("  自动充值金额为 0，跳过")
                    return

                state = adjust_pool_balance(session, amount, "DEPOSIT")
                logger.info(f"  ✅ 自动充值 ¥{amount:.2f}，池余额: ¥{state.pool_balance:.2f}")
        except Exception as e:
            logger.error(f"自动充值失败: {e}", exc_info=True)

    def _job_sync_holdings(self):
        """同步全部基金的持仓数据"""
        logger.info("=== [定时] 持仓同步开始 ===")
        try:
            with Session(engine) as session:
                assets = session.exec(select(Asset)).all()
                for asset in assets:
                    try:
                        sync_fund_holdings(session, asset.code)
                        logger.info(f"  ✅ {asset.code} 持仓同步完成")
                    except Exception as e:
                        logger.warning(f"  ⚠️ {asset.code} 持仓同步失败: {e}")
                logger.info("=== [定时] 持仓同步完成 ===")
        except Exception as e:
            logger.error(f"持仓同步失败: {e}", exc_info=True)
